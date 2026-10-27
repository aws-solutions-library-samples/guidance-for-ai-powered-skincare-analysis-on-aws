"""Opt-in wire/role regression against a dedicated loopback OpenSearch instance.

Run outside pytest (whose default suite prohibits sockets). Creates unique test
indices, users and roles, then removes only those resources. Never targets AWS.
Credentials are read from a local JSON file and are never written to the report.
"""

import argparse
import json
from pathlib import Path
import random
import secrets
import sys
import time
from collections import Counter
from unittest.mock import Mock
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

from opensearchpy import OpenSearch
from opensearchpy.exceptions import AuthorizationException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.search.administration import CatalogAdministration
from agents.search.budget import SearchBudget
from agents.search.opensearch_adapter import OpenSearchExactAdapter, index_mapping
from agents.search.projection import ProjectionWriter
from agents.search.maintenance import CatalogMaintenance
from agents.search.catalog import ingredient_key, summary_key
from agents.search.clients import attribute_map
from tests.integration.test_catalog_publication import MemoryControl
from tests.search_fixtures import configuration, product, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="https://127.0.0.1:19200")
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    url = urlsplit(args.endpoint)
    if url.scheme != "https" or url.hostname not in ("127.0.0.1", "::1", "localhost") or url.username or url.password or url.path or url.query:
        raise ValueError("Use a dedicated HTTPS loopback engine")
    credential = json.loads(args.credentials.read_text())
    def connection(username, password):
        return OpenSearch(
            hosts=[{"host": url.hostname, "port": url.port or 443}], http_auth=(username, password),
            use_ssl=True, verify_certs=False, ssl_assert_hostname=False, ssl_show_warn=False,
            timeout=5, max_retries=0, retry_on_timeout=False,
        )
    admin = connection(credential["username"], credential["password"])
    suffix = uuid4().hex[:12]
    generation, foreign = f"products-wire-{suffix}", f"foreign-wire-{suffix}"
    role_prefix = f"wire_{suffix}_"
    users = {kind: (f"{role_prefix}{kind}", secrets.token_urlsafe(32)) for kind in ("reader", "writer", "maintenance")}
    config = configuration(index_generation=generation)
    created_indices, created_security = [], []
    report = {"engine_version": admin.info()["version"]["number"], "scope": "local engine and FGAC only; AWS IAM/VPC and DynamoDB excluded"}
    try:
        for index in (generation, foreign):
            admin.indices.create(index=index, body={**index_mapping(), "settings": {"number_of_shards": 2, "number_of_replicas": 0}})
            created_indices.append(index)
        def security_request(method, path, **kwargs):
            path = path.replace("/product_", f"/{role_prefix}product_")
            admin.transport.perform_request(method, path, **kwargs)
            created_security.append(path)
        CatalogAdministration(
            None, SimpleNamespace(transport=SimpleNamespace(perform_request=security_request)),
            runtime_role=f"{role_prefix}reader", writer_role=f"{role_prefix}writer",
            maintenance_role=f"{role_prefix}maintenance",
        ).roles()
        for kind, (username, password) in users.items():
            path = f"/_plugins/_security/api/internalusers/{username}"
            admin.transport.perform_request("PUT", path, body={"password": password, "backend_roles": [f"{role_prefix}{kind}"]})
            created_security.append(path)
        writer_client, reader_client = connection(*users["writer"]), connection(*users["reader"])
        writer = ProjectionWriter(writer_client)
        randomizer = random.Random(20261026)
        records = [
            product(
                f"p-{index:04}", ingredient_ids=randomizer.sample(["b3", "c", "c-derivative", "glycerin", "retinol", "fragrance"], randomizer.randint(1, 6)),
                category_id="Cleanser" if index % 3 else "Serum",
                market_ids=[] if index % 7 == 0 else ["GB"],
                currency=None if index % 11 == 0 else "GBP",
                price_minor=None if index % 13 == 0 else (index % 20) * 100,
                active=index % 17 != 0, is_deleted=index % 19 == 0,
                ingredient_list_complete=index % 5 != 0, ingredient_resolution_complete=index % 9 != 0,
                availability=["unknown", "available", "unavailable"][index % 3],
            )
            for index in range(420)
        ]
        for offset in range(0, len(records), 100):
            writer.write(generation, tuple(records[offset:offset + 100]))
        writer_client.indices.refresh(index=generation)
        # Replaying a full document exercises external-version conflict + mget.
        writer.write(generation, (records[1],))
        updated = product(records[1].product_id, source_revision=2, active=False, is_deleted=True)
        writer.write(generation, (updated,))
        writer.write(generation, (records[1],))  # Out-of-order live delivery cannot resurrect it.
        records[1] = updated
        writer_client.indices.refresh(index=generation)
        maint_client = connection(*users["maintenance"])
        search_maintenance = maint_client.search
        def capture_maintenance(**kwargs):
            response = search_maintenance(**kwargs)
            report["last_maintenance_response"] = response
            return response
        maint_client.search = capture_maintenance
        control = MemoryControl(generations=(generation,), CONFIG=config.model_dump(mode="json"))
        for identifier in {identifier for record in records for identifier in record.ingredient_ids}:
            control.records[ingredient_key(config.taxonomy_version, identifier)] = {
                "ingredient_id": identifier, "display_name": identifier, "taxonomy_version": config.taxonomy_version,
                "review_state": "synthetic_fixture", "provenance": "local engine fixture",
            }
        maintenance = CatalogMaintenance(control, Mock(), ProjectionWriter(maint_client), products_table="fixture")
        lease = {"key": "MAINTENANCE_LOCK", "owner": "wire"}
        for _ in range(10):
            maintenance.summary_page(config, lease)
            if control.get("SUMMARY_BUILD")["complete"]:
                break
        assert control.get("SUMMARY_BUILD")["complete"]
        for category in config.categories:
            expected = Counter(identifier for record in records if record.category_id == category and record.active and not record.is_deleted
                               for identifier in record.ingredient_ids)
            summary = control.get(summary_key(config.taxonomy_version, category))
            assert [(item["ingredient_id"], item["count"]) for item in summary["ingredients"]] == sorted(expected.items(), key=lambda item: (-item[1], item[0]))[:30]
        canonical = {record.product_id: record for record in records}
        control.client.get_item.side_effect = lambda **kwargs: {"Item": attribute_map(canonical[kwargs["Key"]["product_id"]["S"]].model_dump(mode="json"))}
        control.records[f"RECONCILIATION#{generation}"] = {"status": "running", "phase": "index", "pit": None}
        for _ in range(10):
            maintenance.reconcile_page(generation, lease)
            if control.get(f"RECONCILIATION#{generation}")["status"] == "complete":
                break
        assert control.get(f"RECONCILIATION#{generation}")["status"] == "complete"
        report["maintenance_snapshot_counts"] = "exact exhaustive agreement"
        report["maintenance_reconciliation"] = "420 indexed identities, revisions, hashes and tombstones checked"
        # New local basic-auth users pay authentication/connection setup once.
        # This is outside the bounded adapter run and is reported explicitly.
        warmup = time.monotonic()
        reader_client.search(index=generation, body={"query": {"match_none": {}}}, params={"request_timeout": 5})
        report["connection_warmup_ms"] = round((time.monotonic() - warmup) * 1000, 2)
        cases = []
        for mode in ("catalog", "purchasable"):
            configured = configuration(index_generation=generation, eligibility_mode=mode)
            adapter = OpenSearchExactAdapter(reader_client, configured)
            for index in range(60):
                preferred = tuple(randomizer.sample(["b3", "c", "c-derivative", "glycerin", "retinol", "absent"], 3))
                required = ("glycerin",) if index % 3 == 0 else ()
                excluded = ("fragrance",) if index % 4 == 0 else ()
                cap = 700 if index % 5 == 0 else None
                wanted = request(
                    index_generation=generation, eligibility_mode=mode,
                    category_id="Serum" if index % 2 else "Cleanser",
                    preferred_ingredient_ids=preferred, must_have_ingredient_ids=required,
                    excluded_ingredient_ids=excluded, max_price_minor=cap,
                )
                # Independent exhaustive oracle: do not call the application's predicate/query builder.
                scored = []
                for record in records:
                    present = set(record.ingredient_ids)
                    count = len(set(preferred) & present)
                    if (not record.active or record.is_deleted or record.category_id != wanted.category_id
                        or "GB" not in record.market_ids or record.currency != "GBP"
                        or not set(required) <= present or set(excluded) & present
                        or (excluded and not (record.ingredient_list_complete and record.ingredient_resolution_complete))
                        or (cap is not None and (record.price_minor is None or record.price_minor > cap))
                        or (mode == "purchasable" and record.availability != "available") or count == 0):
                        continue
                    scored.append((record.product_id, count))
                expected = sorted(scored, key=lambda item: (-item[1], item[0]))[:100]
                actual = adapter.retrieve(wanted, SearchBudget())
                assert [(item.product_id, int(item.score)) for item in actual] == expected
                cases.append(len(actual))
        denied = []
        for label, operation in [
            ("reader_write", lambda: reader_client.index(index=generation, id="forbidden", body={})),
            ("reader_mget", lambda: reader_client.mget(index=generation, body={"ids": ["fixture/p-0001"]})),
            ("reader_foreign_index", lambda: reader_client.search(index=foreign, body={"query": {"match_all": {}}})),
            ("writer_search", lambda: writer_client.search(index=generation, body={"query": {"match_all": {}}})),
            ("writer_create_index", lambda: writer_client.indices.create(index=f"products-forbidden-{suffix}")),
            ("maintenance_create_index", lambda: maint_client.indices.create(index=f"products-forbidden-{suffix}")),
            ("maintenance_foreign_index", lambda: maint_client.search(index=foreign, body={"query": {"match_all": {}}})),
        ]:
            try:
                operation()
            except AuthorizationException:
                denied.append(label)
            else:
                raise AssertionError(f"Role unexpectedly permitted {label}")
        report.update(records=len(records), oracle_requests=len(cases), ordered_top100_differences=0,
                      denied_operations=denied, duplicate_and_stale_publication="passed", completed_at=time.time())
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc), failed_at=time.time())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        raise
    finally:
        forbidden = f"products-forbidden-{suffix}"
        if admin.indices.exists(index=forbidden):
            admin.indices.delete(index=forbidden)
        for index in created_indices:
            admin.indices.delete(index=index)
        for path in reversed(created_security):
            admin.transport.perform_request("DELETE", path)
    report["temporary_resources_removed"] = True
    report.pop("last_maintenance_response", None)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
