"""Opt-in, bounded DynamoDB publication qualification with disposable tables.

Requires --execute and an explicit account. Never touches application tables.
This verifies managed DynamoDB only, not OpenSearch, models or capacity targets.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.search.clients import attribute_map, native_map
from agents.search.publication import (
    CatalogPublisher, ControlStore, Outbox, OUTBOX_SHARDS, product_shard,
    publication_locks, shard_key, source_watermarks,
)
from tests.search_fixtures import product


class BoundedClient:
    def __init__(self, client, *, limit=2000):
        self.client, self.limit, self.calls = client, limit, Counter()
        self.lock = threading.Lock()
        self.deadline = time.monotonic() + 300

    def __getattr__(self, name):
        method = getattr(self.client, name)
        def call(**kwargs):
            with self.lock:
                if sum(self.calls.values()) >= self.limit or time.monotonic() > self.deadline:
                    raise RuntimeError("AWS test request/time budget exhausted")
                self.calls[name] += 1
            return method(**kwargs)
        return call


def wait_table(client, name, *, deleted=False):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            table = client.describe_table(TableName=name)["Table"]
            if not deleted and table["TableStatus"] == "ACTIVE":
                return table
        except client.exceptions.ResourceNotFoundException:
            if deleted:
                return None
            raise
        time.sleep(1)
    raise RuntimeError(f"Table lifecycle timed out: {name}")


def run(args):
    if args.region != "eu-west-1":
        raise ValueError("This recorded price budget is specific to eu-west-1")
    # Current official 2026-10-27 prices. The fixtures are <4 KiB, pages <=100,
    # and transactions <=17 small records. 100 units of BOTH read and write
    # per API call is deliberately pessimistic. No SDK retries are enabled.
    reserve = 2000 * 100 * (0.0000007050 + 0.0000001415) + 0.01
    if reserve >= 1:
        raise ValueError("The bounded test no longer fits its USD 1 reservation")
    if not args.execute:
        print(json.dumps({"execute": False, "usd_reserved": 1, "estimated_upper_usd": reserve}))
        return
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    actual_account = session.client("sts").get_caller_identity()["Account"]
    if actual_account != args.account:
        raise ValueError("AWS account differs from the explicitly approved account")
    raw = session.client("dynamodb", config=Config(
        retries={"total_max_attempts": 1}, connect_timeout=2, read_timeout=5, max_pool_connections=16,
    ))
    client = BoundedClient(raw)
    run_id = uuid4().hex[:16]
    names = {kind: f"smart-beauty-test-publication-{run_id}-{kind}" for kind in ("products", "metadata", "outbox")}
    report = {
        "run_id": run_id, "account": actual_account, "region": args.region,
        "scope": "managed DynamoDB transactions, sharded outbox and lease fencing only",
        "usd_reserved": 1, "estimated_upper_usd": reserve,
        "tables": names, "started_at": time.time(), "status": "running",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    attempted, cleanup_errors = [], []
    try:
        for kind, name in names.items():
            key = {"products": "product_id", "metadata": "pk", "outbox": "catalog_shard"}[kind]
            schema = [{"AttributeName": key, "KeyType": "HASH"}]
            attributes = [{"AttributeName": key, "AttributeType": "S"}]
            if kind == "outbox":
                schema.append({"AttributeName": "sequence", "KeyType": "RANGE"})
                attributes.append({"AttributeName": "sequence", "AttributeType": "N"})
            attempted.append(name)
            client.create_table(
                TableName=name, KeySchema=schema, AttributeDefinitions=attributes,
                BillingMode="PAY_PER_REQUEST", SSESpecification={"Enabled": True},
                Tags=[{"Key": "Project", "Value": "smart-beauty"}, {"Key": "QualificationRun", "Value": run_id}],
            )
        for name in names.values():
            wait_table(raw, name)
        control = ControlStore(client, names["metadata"], "fixture")
        control.put("SOURCE", {"healthy": True, "mode": "snapshot"})
        for shard in range(OUTBOX_SHARDS):
            control.put(shard_key("SOURCE", shard), {"sequence": 0})
        publisher = CatalogPublisher(client, products_table=names["products"], outbox_table=names["outbox"], control=control)
        # One record per shard, so concurrent independent updates have no
        # intentional hot-key contention. Duplicate/revision races follow.
        records = {}
        index = 0
        while len(records) < OUTBOX_SHARDS:
            record = product(f"cloud-{index}")
            records.setdefault(product_shard(record.product_id), record)
            index += 1
        assert all(len(record.model_dump_json().encode()) < 4096 for record in records.values())
        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(publisher.publish, records.values()))
        assert outcomes == ["published"] * OUTBOX_SHARDS
        first = records[0]
        with ThreadPoolExecutor(max_workers=4) as executor:
            assert list(executor.map(publisher.publish, [first] * 4)) == ["duplicate"] * 4
        newer = product(first.product_id, source_revision=3, active=False, is_deleted=True)
        assert publisher.publish(newer) == "published"
        assert publisher.publish(product(first.product_id, source_revision=2)) == "stale"
        try:
            publisher.publish(product(first.product_id, source_revision=3, name="Conflicting revision"))
        except ValueError:
            pass
        else:
            raise AssertionError("Equal revision with changed content was accepted")
        outbox = Outbox(client, names["outbox"], "fixture")
        for shard, watermark in source_watermarks(control).items():
            rows = outbox.after(shard, 0)
            assert len(rows) == watermark == (2 if shard == 0 else 1)
            assert len({row["event_id"] for row in rows}) == len(rows)
            assert all(product_shard(row["product"]["product_id"]) == shard for row in rows)
        canonical = native_map(client.get_item(
            TableName=names["products"], Key=attribute_map({"product_id": first.product_id}), ConsistentRead=True,
        )["Item"])
        assert canonical["source_revision"] == 3 and canonical["is_deleted"] is True
        with control.lock(keys=(*publication_locks(), "MAINTENANCE_LOCK")) as lease:
            control.transaction({"FENCED_TEST": {"value": "committed"}}, lease=lease)
            assert control.get("FENCED_TEST") == {"value": "committed"}
            try:
                with control.lock(keys=("PROJECTION_LOCK#05",)):
                    raise AssertionError("Competing lease entered")
            except ClientError as exc:
                assert exc.response["Error"]["Code"] == "TransactionCanceledException"
        # The released owner's token must not authorize a later write.
        try:
            control.put("FENCED_TEST", {"value": "stale"}, lease=lease)
        except ClientError as exc:
            assert exc.response["Error"]["Code"] == "TransactionCanceledException"
        else:
            raise AssertionError("Released lease authorized a stale writer")
        assert control.get("FENCED_TEST") == {"value": "committed"}
        report.update(status="passed", published_events=17, shards_checked=16, completed_at=time.time())
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        # Verify ownership by the run tag, including ambiguous create responses.
        # Cleanup does not consume the work budget; it must remain possible.
        for name in attempted:
            try:
                try:
                    table = wait_table(raw, name)
                except raw.exceptions.ResourceNotFoundException:
                    continue
                tags = raw.list_tags_of_resource(ResourceArn=table["TableArn"])["Tags"]
                if {"Key": "QualificationRun", "Value": run_id} not in tags:
                    raise RuntimeError("Refusing cleanup of a table without this run's ownership tag")
                raw.delete_table(TableName=name)
                wait_table(raw, name, deleted=True)
            except Exception as exc:
                cleanup_errors.append({"table": name, "error": str(exc)})
        report.update(api_calls=dict(client.calls), cleanup_errors=cleanup_errors, cleanup_verified=not cleanup_errors)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    if cleanup_errors:
        raise RuntimeError("Qualification resources require cleanup; see report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    run(parser.parse_args())
