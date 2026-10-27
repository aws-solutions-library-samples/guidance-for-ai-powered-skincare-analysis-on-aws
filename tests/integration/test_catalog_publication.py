"""Exercise publication boundaries with real serializers and controlled I/O."""

from contextlib import nullcontext
from copy import deepcopy
import importlib.util
import json
import time
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from agents.search.administration import CatalogAdministration
from agents.search.clients import attribute_map, native_map
from agents.search.normalization import IngredientRegistry, normalize_product
from agents.search.opensearch_adapter import document_id, search_document
from agents.search.projection import ProjectionWorker, ProjectionWriter
from agents.search.maintenance import CatalogMaintenance
from agents.search.publication import CatalogPublisher, ControlStore, Outbox, OUTBOX_SHARDS, product_shard, shard_key
from tests.search_fixtures import configuration, product, readiness


class MemoryControl:
    def __init__(self, *, sequence=0, generations=("products-fixture-v1",), **records):
        self.catalog_id, self.table, self.client = "fixture", "metadata", Mock()
        self.records = {
            "CONFIG": configuration().model_dump(mode="json"),
            "SOURCE": {"mode": "snapshot", "healthy": True},
            "PROJECTION": {"generations": list(generations)},
            "CONFIG_HISTORY#products-fixture-v1": configuration().model_dump(mode="json"),
            "READINESS#products-fixture-v1": readiness().model_dump(),
        }
        for shard in range(OUTBOX_SHARDS):
            self.records[shard_key("SOURCE", shard)] = {"sequence": sequence}
            self.records[shard_key("PROJECTION", shard)] = {
                "generations": {generation: {"sequence": sequence, "error": None} for generation in generations},
            }
        for generation in generations:
            self.records[f"RECONCILIATION#{generation}"] = {
                "status": "complete", "completed_at": time.time(), "error": None,
            }
        self.records.update(records)
        self.writes = []

    def lock(self, **kwargs):
        return nullcontext({"key": kwargs.get("keys", ("PROJECTION_LOCK",))[0], "owner": "test-lease"})

    def get(self, key):
        return deepcopy(self.records.get(key))

    def put(self, key, value, **kwargs):
        self.writes.append(key)
        self.records[key] = deepcopy(value)

    def transaction(self, records, *, lease, checks=()):
        ControlStore.transaction(self, records, lease=lease, checks=checks)
        self.records.update(deepcopy(records))


def event(record, sequence=1):
    return {
        "sequence": sequence, "accepted_at": time.time(), "product": record.model_dump(mode="json"),
        "event_id": f"{record.catalog_id}/{record.product_id}/{record.source_revision}",
    }


def bulk_result(record, status=201):
    return {"index": {
        "_index": "products-fixture-v1", "_id": document_id(record.catalog_id, record.product_id),
        "_version": record.source_revision, "status": status,
    }}


def publisher(existing=None):
    client = Mock()
    client.get_item.return_value = {"Item": attribute_map(existing.model_dump(mode="json"))} if existing else {}
    control = MemoryControl()
    return CatalogPublisher(client, products_table="products", outbox_table="outbox", control=control), client


def test_canonical_product_and_outbox_share_one_conditional_transaction():
    publish, client = publisher()
    record = product()
    assert publish.publish(record) == "published"
    writes = client.transact_write_items.call_args.kwargs["TransactItems"]
    assert len(writes) == 3
    assert native_map(writes[0]["Put"]["Item"])["record_hash"] == record.record_hash
    event = native_map(writes[1]["Put"]["Item"])
    assert event["product"]["source_revision"] == 1 and event["sequence"] == 1
    assert event["catalog_id"] == "fixture" and event["previous_category"] is None
    assert event["event_id"] == f"fixture/{record.product_id}/1"
    assert event["catalog_shard"] == f"fixture#{product_shard(record.product_id):02d}"
    assert writes[2]["Update"]["Key"] == attribute_map({"pk": shard_key("SOURCE", product_shard(record.product_id))})
    assert writes[2]["Update"]["ConditionExpression"] == "#value.#sequence = :previous"
    assert "ConditionExpression" in writes[0]["Put"] and "ConditionExpression" in writes[1]["Put"]


@pytest.mark.parametrize("incoming,expected", [(product(), "duplicate"), (product(source_revision=1), "stale")])
def test_duplicate_and_out_of_order_deliveries_do_not_write(incoming, expected):
    publish, client = publisher(product(source_revision=2) if expected == "stale" else product())
    assert publish.publish(incoming) == expected
    client.transact_write_items.assert_not_called()


def test_equal_revision_with_changed_content_is_rejected():
    publish, client = publisher(product())
    with pytest.raises(ValueError, match="Same supplier revision"):
        publish.publish(product(name="Conflicting supplier content"))
    client.transact_write_items.assert_not_called()


def test_publication_conflict_rereads_canonical_and_does_not_duplicate_the_event():
    publish, client = publisher()
    client.get_item.side_effect = [{}, {"Item": attribute_map(product().model_dump(mode="json"))}]
    client.transact_write_items.side_effect = ClientError({
        "Error": {"Code": "TransactionCanceledException"},
        "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}, {"Code": "None"}],
    }, "TransactWriteItems")
    assert publish.publish(product()) == "duplicate"
    assert client.transact_write_items.call_count == 1


def test_projection_sends_full_external_versions_and_retains_tombstones():
    record = product(source_revision=7, active=False, is_deleted=True)
    client = Mock()
    client.bulk.return_value = {"errors": False, "items": [bulk_result(record)]}
    ProjectionWriter(client).write("products-fixture-v1", (record,))
    action, source = map(json.loads, client.bulk.call_args.kwargs["body"].splitlines())
    assert action["index"]["version_type"] == "external" and action["index"]["version"] == 7
    assert source == search_document(record) and source["is_deleted"] is True
    client.delete.assert_not_called()


@pytest.mark.parametrize("change", [{}, {"active": False}, {"matching_hash": "a" * 64}])
def test_duplicate_projection_conflict_verifies_all_equal_revision_facts(change):
    record = product()
    client = Mock()
    client.bulk.return_value = {"errors": True, "items": [bulk_result(record, 409)]}
    client.mget.return_value = {"docs": [{
        "_index": "products-fixture-v1", "_id": document_id("fixture", record.product_id),
        "_version": 1, "found": True, "_source": {**search_document(record), **change},
    }]}
    writer = ProjectionWriter(client)
    if change:
        with pytest.raises(RuntimeError, match="inconsistent source"):
            writer.write("products-fixture-v1", (record,))
    else:
        writer.write("products-fixture-v1", (record,))


def test_partial_bulk_failure_keeps_checkpoint_and_invalidates_readiness():
    record = product()
    shard = product_shard(record.product_id)
    other = next(f"other-{index}" for index in range(1000) if product_shard(f"other-{index}") == shard)
    records = (record, product(other))
    control, outbox, client = MemoryControl(), Mock(), Mock()
    control.records[shard_key("SOURCE", shard)] = {"sequence": 2}
    outbox.after.return_value = [event(record, i) for i, record in enumerate(records, 1)]
    client.bulk.return_value = {"errors": True, "items": [bulk_result(records[0]), bulk_result(records[1], 429)]}
    worker = ProjectionWorker(control, outbox, ProjectionWriter(client), products_table="products")
    assert worker.run(shard)["failures"] == {"products-fixture-v1": "RuntimeError"}
    ack = control.get(shard_key("PROJECTION", shard))["generations"]["products-fixture-v1"]
    assert ack["sequence"] == 0 and ack["error"]["event_ids"] == [row["event_id"] for row in outbox.after.return_value]
    assert control.get("READINESS#products-fixture-v1")["healthy"] is False
    client.indices.refresh.assert_not_called()


def test_worker_refreshes_every_retained_generation_before_advancing_checkpoint():
    record = product()
    shard = product_shard(record.product_id)
    control = MemoryControl(generations=("products-fixture-v1", "products-next"))
    control.records[shard_key("SOURCE", shard)] = {"sequence": 1}
    outbox, writer = Mock(), Mock()
    outbox.after.side_effect = lambda shard, sequence: [event(record)] if sequence == 0 else []
    writer.client.cluster.health.return_value = {"status": "green", "timed_out": False}
    worker = ProjectionWorker(control, outbox, writer, products_table="products")
    assert all(state["sequence"] == 1 for state in worker.run(shard)["generations"].values())
    assert [call.args[0] for call in writer.write.call_args_list] == ["products-fixture-v1", "products-next"]
    assert writer.client.indices.refresh.call_count == 2
    control.client.delete_item.assert_not_called()  # Maintenance atomically replaces advisory snapshots.


def test_backfill_resumes_its_saved_cursor_and_keeps_deleted_products():
    cursor = attribute_map({"product_id": "last-page"})
    control = MemoryControl(REBUILD={"generation": "products-next", "cursor": cursor, "complete": False})
    control.client.scan.return_value = {"Items": [attribute_map(product(active=False, is_deleted=True).model_dump(mode="json"))]}
    outbox, writer = Mock(), Mock()
    outbox.after.return_value = []
    writer.client.cluster.health.return_value = {"status": "green", "timed_out": False}
    CatalogMaintenance(control, outbox, writer, products_table="products").backfill_page({"key": "MAINTENANCE_LOCK", "owner": "test"})
    assert control.client.scan.call_args.kwargs == {"TableName": "products", "Limit": 100, "ConsistentRead": True, "ExclusiveStartKey": cursor}
    assert writer.write.call_args.args[1][0].is_deleted is True
    assert control.get("REBUILD")["complete"] is True


def test_outbox_gap_never_advances_a_checkpoint():
    client = Mock()
    client.query.return_value = {"Items": [attribute_map({"catalog_id": "fixture", "sequence": 3})]}
    with pytest.raises(ValueError, match="gap"):
        Outbox(client, "outbox", "fixture").after(0, 1)


def test_cutover_requires_completed_backfill_and_uses_a_source_watermark_transaction():
    control = MemoryControl(
        sequence=10, generations=("products-fixture-v1", "products-next"),
        REBUILD={"generation": "products-next", "complete": False},
    )
    search = Mock()
    search.cluster.health.return_value = {"status": "green", "timed_out": False}
    admin = CatalogAdministration(control, search, runtime_role="reader", writer_role="writer")
    with pytest.raises(ValueError, match="incomplete"):
        admin.activate("products-next")
    search.indices.update_aliases.assert_not_called()
    control.records["REBUILD"]["complete"] = True
    assert admin.activate("products-next")["status"] == "activated"
    items = control.client.transact_write_items.call_args.kwargs["TransactItems"]
    checks = [item["ConditionCheck"] for item in items if "ConditionCheck" in item]
    counters = [item for item in checks if item["Key"]["pk"]["S"].startswith("SOURCE#")]
    assert len(counters) == 16
    assert all(native_map(item["ExpressionAttributeValues"])[":sequence"] == 10 for item in counters)
    assert checks[0]["Key"]["pk"]["S"] == "PROJECTION_LOCK#00"
    config = next(native_map(item["Put"]["Item"])["value"] for item in items if "Put" in item and item["Put"]["Item"]["pk"]["S"] == "CONFIG")
    assert config["index_generation"] == "products-next"


def test_initializer_rejects_silent_semantic_configuration_changes():
    admin = CatalogAdministration(MemoryControl(), Mock(), runtime_role="reader", writer_role="writer")
    with pytest.raises(ValueError, match="explicit migration"):
        admin.initialize(configuration(categories=("Cleanser", "Moisturizer")), Mock())


def test_demo_source_is_explicit_and_real_feed_unknowns_stay_unknown(tmp_path):
    module = migration_module()
    root = Path(__file__).resolve().parents[2]
    config = configuration(catalog_id="demo", taxonomy_version="demo-v1", categories=tuple(json.loads((root / "data/search-config.json").read_text())["categories"]))
    registry = IngredientRegistry(json.loads((root / "data/ingredient-registry.json").read_text()), "demo-v1")
    rows = list(module.source_rows(root / "data/products.csv", demo=True))
    assert len(rows) == len({row["product_id"] for row in rows}) == 48
    products = [normalize_product(row, registry, config) for row in rows]
    assert all(row.ingredient_resolution_complete and row.ingredient_list_complete for row in products)
    assert all(row.availability == "unknown" for row in products)
    feed = tmp_path / "feed.jsonl"
    raw = {key: value for key, value in rows[0].items() if key not in ("price_minor", "currency", "market_ids", "ingredient_list_complete")}
    feed.write_text(json.dumps(raw) + "\n")
    canonical = normalize_product(next(module.source_rows(feed, demo=False)), registry, config)
    assert canonical.price_minor is canonical.currency is None
    assert canonical.market_ids == () and canonical.ingredient_list_complete is False


def migration_module():
    path = Path(__file__).resolve().parents[2] / "scripts/migrate_products.py"
    spec = importlib.util.spec_from_file_location("migrate_products", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_watermarks_with_unhealthy_readiness_are_not_ready(monkeypatch):
    module = migration_module()
    control = MemoryControl()
    control.records["READINESS#products-fixture-v1"]["healthy"] = False
    monkeypatch.setattr(module.time, "monotonic", Mock(side_effect=[0, 0, 301]))
    monkeypatch.setattr(module.time, "sleep", Mock())
    with pytest.raises(RuntimeError, match="become ready"):
        module.wait_until_ready(control)


@pytest.mark.parametrize("marker,resumes", [(None, False), ({"status": "complete"}, False), ({"status": "in_progress"}, True)])
def test_demo_resume_cannot_overwrite_an_unhealthy_supplier_import(monkeypatch, tmp_path, marker, resumes):
    module = migration_module()
    root = Path(__file__).resolve().parents[2]
    control = MemoryControl(sequence=2, SOURCE={"mode": "snapshot", "healthy": False})
    if marker:
        control.records["DEMO_IMPORT"] = marker
    publish = Mock()
    publish.publish.return_value = "duplicate"
    monkeypatch.setattr(module, "ControlStore", lambda *args: control)
    monkeypatch.setattr(module, "CatalogPublisher", lambda *args, **kwargs: publish)
    monkeypatch.setattr(module, "dynamodb_resource", lambda *args, **kwargs: SimpleNamespace(client=Mock()))
    monkeypatch.setattr(module, "source_rows", lambda *args, **kwargs: iter([{}]))
    monkeypatch.setattr(module, "normalize_product", lambda *args: product())
    args = SimpleNamespace(
        config=root / "data/search-config.json", registry=root / "data/ingredient-registry.json",
        metadata_table="metadata", products_table="products", outbox_table="outbox",
        admin_function=None, demo_if_empty=True, wait_ready=False, source=tmp_path / "ignored.csv", feed_mode="snapshot",
    )
    if resumes:
        module.migrate(args)
        publish.publish.assert_called_once()
        assert control.get("DEMO_IMPORT") == {"status": "complete"}
    else:
        with pytest.raises(ValueError, match="supplier feed"):
            module.migrate(args)
        publish.set_source_health.assert_not_called()


def test_demo_import_preserves_the_summary_published_while_waiting_for_readiness(monkeypatch):
    from agents.search.catalog import summary_key
    module = migration_module()
    root = Path(__file__).resolve().parents[2]
    control = MemoryControl()
    publish = Mock()
    publish.publish.return_value = "published"
    monkeypatch.setattr(module, "ControlStore", lambda *args: control)
    monkeypatch.setattr(module, "CatalogPublisher", lambda *args, **kwargs: publish)
    monkeypatch.setattr(module, "dynamodb_resource", lambda *args, **kwargs: SimpleNamespace(client=Mock()))
    key = summary_key("demo-v1", "Cleanser")
    snapshot = {
        "category_id": "Cleanser", "taxonomy_version": "demo-v1",
        "index_generation": "products-demo-v1", "as_of": 1234, "ingredients": [],
    }
    monkeypatch.setattr(module, "wait_until_ready", lambda control: control.put(key, snapshot))
    module.migrate(SimpleNamespace(
        config=root / "data/search-config.json", registry=root / "data/ingredient-registry.json",
        metadata_table="metadata", products_table="products", outbox_table="outbox",
        admin_function=None, demo_if_empty=True, wait_ready=True,
        source=root / "data/products.csv", feed_mode="snapshot",
    ))
    assert publish.publish.call_count == 48
    assert control.get(key) == snapshot


def test_rebuild_registration_is_atomic_and_rollback_retention_is_seven_days(monkeypatch):
    control, search = MemoryControl(), Mock()
    admin = CatalogAdministration(control, search, runtime_role="reader", writer_role="writer")
    monkeypatch.setattr(admin, "create_index", Mock())
    admin.start_rebuild("products-next")
    items = control.client.transact_write_items.call_args.kwargs["TransactItems"]
    assert {item["Put"]["Item"]["pk"]["S"] for item in items if "Put" in item} == {
        "PROJECTION", "REBUILD", "GENERATION#products-next", *(shard_key("PROJECTION", shard) for shard in range(OUTBOX_SHARDS)),
    }
    control.records["LAST_CUTOVER"] = {"at": 1000, "previous": "products-previous"}
    monkeypatch.setattr("agents.search.administration.time.time", lambda: 1000 + 86400)
    with pytest.raises(ValueError, match="retention"):
        admin.retire("products-previous")


def test_entrypoint_emits_heartbeats_and_cancels_silent_work(monkeypatch):
    import asyncio
    import agentcore_entrypoint as entrypoint
    monkeypatch.setattr(entrypoint, "HEARTBEAT_SECONDS", 0.005)
    monkeypatch.setattr(entrypoint, "ROUTINE_DEADLINE_SECONDS", 0.025)
    closed, events = [], []
    async def source():
        try:
            await asyncio.Event().wait()
            yield {}
        finally:
            closed.append(True)
    async def run():
        from agents.errors import AnalysisFailure
        with pytest.raises(AnalysisFailure) as failure:
            async for event in entrypoint.bounded_events(source()):
                events.append(event)
        assert failure.value.code == "TIMEOUT"
    asyncio.run(run())
    assert events and all(event == {"type": "heartbeat"} for event in events)
    assert closed == [True]
