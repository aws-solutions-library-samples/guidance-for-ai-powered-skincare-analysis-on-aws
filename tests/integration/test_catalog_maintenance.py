"""Recovery, independent generation progress and bounded maintenance pages."""

from copy import deepcopy
import time
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from agents.search.catalog import ingredient_key, summary_key
from agents.search.clients import attribute_map
from agents.search.errors import CatalogIntegrityError
from agents.search.maintenance import CatalogMaintenance
from agents.search.opensearch_adapter import document_id, search_document
from agents.search.projection import ProjectionWorker
from agents.search.publication import ControlStore, product_shard, shard_key, source_is_healthy
from tests.integration.test_catalog_publication import MemoryControl, event
from tests.search_fixtures import configuration, product

GENERATION = "products-fixture-v1"
LEASE = {"key": "MAINTENANCE_LOCK", "owner": "test"}


def maintenance(control=None):
    control, outbox, writer = control or MemoryControl(), Mock(), Mock()
    outbox.after.return_value = []
    writer.client.cluster.health.return_value = {"status": "green", "timed_out": False}
    return CatalogMaintenance(control, outbox, writer, products_table="products")


def test_failed_rollback_generation_does_not_delay_active_acknowledgements():
    record = product()
    shard = product_shard(record.product_id)
    control = MemoryControl(generations=(GENERATION, "products-broken"))
    control.records[shard_key("SOURCE", shard)] = {"sequence": 1}
    outbox, writer = Mock(), Mock()
    outbox.after.side_effect = lambda shard, sequence: [event(record)] if sequence == 0 else []
    def write(generation, products):
        if generation == "products-broken":
            raise RuntimeError("unavailable retained shard")
    writer.write.side_effect = write
    result = ProjectionWorker(control, outbox, writer, products_table="products").run(shard)
    assert result["generations"][GENERATION] == {"sequence": 1, "error": None}
    assert result["generations"]["products-broken"]["sequence"] == 0
    assert result["failures"] == {"products-broken": "RuntimeError"}
    writer.write.side_effect = None
    recovered = ProjectionWorker(control, outbox, writer, products_table="products").run(shard)
    assert recovered["generations"]["products-broken"] == {"sequence": 1, "error": None}


def test_expired_worker_cannot_store_an_acknowledgement_or_remove_new_owner():
    client = Mock()
    client.transact_write_items.side_effect = ClientError({
        "Error": {"Code": "TransactionCanceledException"},
        "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}],
    }, "TransactWriteItems")
    control = ControlStore(client, "metadata", "fixture")
    with pytest.raises(ClientError):
        control.put("PROJECTION#00", {"sequence": 100}, lease={"key": "PROJECTION_LOCK#00", "owner": "expired"})
    operations = client.transact_write_items.call_args.kwargs["TransactItems"]
    assert operations[0]["ConditionCheck"]["ConditionExpression"] == "#owner = :owner AND expires_at > :now"
    assert operations[0]["ConditionCheck"]["ExpressionAttributeValues"][":owner"] == {"S": "expired"}
    assert operations[1]["Put"]["Item"]["pk"]["S"] == "PROJECTION#00"


@pytest.mark.parametrize("source,healthy", [
    (None, False), ({"healthy": True}, False),
    ({"healthy": True, "mode": "snapshot"}, True),
    ({"healthy": False, "mode": "snapshot"}, False),
    ({"healthy": True, "mode": "live", "checked_at": 100}, True),
    ({"healthy": True, "mode": "live", "checked_at": 39}, False),
    ({"healthy": True, "mode": "live", "checked_at": 101}, False),
])
def test_missing_live_feed_heartbeat_is_distinct_from_idle_snapshot(source, healthy):
    assert source_is_healthy(source, now=100) is healthy


def test_capture_gap_marks_readiness_unhealthy_without_stalling_other_maintenance():
    job = maintenance()
    job.control.records["SOURCE#00"] = {"sequence": 3}
    result = job.heartbeat()[GENERATION]
    assert result["healthy"] is False
    assert job.control.get(f"READINESS#{GENERATION}")["healthy"] is False


def test_oldest_pending_change_is_taken_across_all_shards():
    job = maintenance()
    job.control.records["SOURCE#03"] = {"sequence": 1}
    job.control.records["SOURCE#14"] = {"sequence": 1}
    now = time.time()
    job.outbox.after.side_effect = lambda shard, sequence, limit: [{"accepted_at": now - (80 if shard == 3 else 10)}]
    metrics = job.heartbeat()[GENERATION]
    assert metrics["healthy"] is True and metrics["lag_seconds"] >= 80
    assert job.control.get(f"READINESS#{GENERATION}")["oldest_pending_at"] == now - 80


def test_reconciliation_checks_tombstones_and_quarantines_unknown_index_identity():
    job = maintenance()
    record = product(active=False, is_deleted=True)
    job.control.records.pop(f"RECONCILIATION#{GENERATION}")
    job.control.client.scan.return_value = {"Items": [attribute_map(record.model_dump(mode="json"))]}
    job.reconcile_page(GENERATION, LEASE)
    assert job.writer.write.call_args.args[1] == (record,)
    assert job.control.get(f"RECONCILIATION#{GENERATION}")["phase"] == "index"
    job.search.create_pit.return_value = {"pit_id": "snapshot", "_shards": {"total": 2, "successful": 2, "failed": 0}}
    job.search.search.return_value = search_response([hit(record)])
    job.control.client.get_item.return_value = {}
    job.reconcile_page(GENERATION, LEASE)
    state = job.control.get(f"RECONCILIATION#{GENERATION}")
    assert state["status"] == "quarantined" and "no canonical identity" in state["error"]
    assert job.heartbeat()[GENERATION]["healthy"] is False
    job.search.delete.assert_not_called()


def hit(record):
    return {
        "_index": GENERATION, "_id": document_id(record.catalog_id, record.product_id),
        "_version": record.source_revision, "_source": search_document(record), "sort": [record.product_id],
    }


def search_response(hits=(), aggregation=None):
    result = {
        "timed_out": False, "_shards": {"total": 2, "successful": 2, "failed": 0, "skipped": 0},
        "hits": {"hits": list(hits)},
    }
    if aggregation is not None:
        result["aggregations"] = {"ingredients": aggregation}
    return result


def test_reconciliation_accepts_ongoing_newer_canonical_update_and_replays_it():
    job = maintenance()
    current, observed = product(source_revision=2), product()
    job.control.client.get_item.return_value = {"Item": attribute_map(current.model_dump(mode="json"))}
    job._verify_index_page(GENERATION, [hit(observed)])
    job.writer.write.assert_called_once_with(GENERATION, (current,))
    assert job.control.client.get_item.call_args.kwargs["ConsistentRead"] is True


@pytest.mark.parametrize("change", [
    {"_id": "fixture/unrequested"}, {"_version": 2},
    {"_source": search_document(product(active=False))}, {"sort": ["elsewhere"]},
])
def test_reconciliation_rejects_equal_revision_corruption(change):
    job = maintenance()
    record = product()
    job.control.client.get_item.return_value = {"Item": attribute_map(record.model_dump(mode="json"))}
    with pytest.raises(CatalogIntegrityError):
        job._verify_index_page(GENERATION, [{**hit(record), **change}])
    job.writer.write.assert_not_called()


def test_canonical_side_equal_revision_conflict_is_quarantined():
    job = maintenance()
    job.control.records.pop(f"RECONCILIATION#{GENERATION}")
    job.control.client.scan.return_value = {"Items": [attribute_map(product().model_dump(mode="json"))]}
    job.writer.write.side_effect = CatalogIntegrityError("Equal revision differs")
    job.reconcile_page(GENERATION, LEASE)
    assert job.control.get(f"RECONCILIATION#{GENERATION}")["status"] == "quarantined"


def test_summaries_paginate_one_snapshot_keep_top_thirty_and_replace_empty_categories():
    job = maintenance()
    config = configuration(categories=("Cleanser", "Serum"))
    job.search.create_pit.return_value = {"pit_id": "fixed-snapshot", "_shards": {"total": 2, "successful": 2, "failed": 0}}
    entries = [{"ingredient_id": f"i-{index:02}", "count": (index % 7) + 1} for index in range(45)]
    for entry in entries:
        job.control.records[ingredient_key(config.taxonomy_version, entry["ingredient_id"])] = {
            "ingredient_id": entry["ingredient_id"], "display_name": entry["ingredient_id"],
            "taxonomy_version": config.taxonomy_version, "review_state": "synthetic_fixture", "provenance": "fixture",
        }
    def page(part):
        return {
            "buckets": [{"key": {"category": "Cleanser", "ingredient": entry["ingredient_id"]}, "doc_count": entry["count"]} for entry in part],
            **({"after_key": {"category": "Cleanser", "ingredient": part[-1]["ingredient_id"]}} if part else {}),
        }
    job.search.search.side_effect = [search_response(aggregation=page(part)) for part in (entries[:20], entries[20:], [])]
    job.summary_page(config, LEASE)
    first = deepcopy(job.control.get("SUMMARY_BUILD"))
    assert job.control.get(summary_key(config.taxonomy_version, "Cleanser")) is None
    job.summary_page(config, LEASE)
    job.summary_page(config, LEASE)
    summary = job.control.get(summary_key(config.taxonomy_version, "Cleanser"))
    expected = sorted(entries, key=lambda item: (-item["count"], item["ingredient_id"]))[:30]
    assert [(item["ingredient_id"], item["count"]) for item in summary["ingredients"]] == [
        (item["ingredient_id"], item["count"]) for item in expected]
    assert summary["as_of"] == first["as_of"] and summary["index_generation"] == GENERATION
    assert job.control.get(summary_key(config.taxonomy_version, "Serum"))["ingredients"] == []
    assert job.search.create_pit.call_count == 1
    assert all(call.kwargs["body"]["pit"]["id"] == "fixed-snapshot" for call in job.search.search.call_args_list)
    job.search.delete_pit.assert_called_once_with(body={"pit_id": ["fixed-snapshot"]}, params={"request_timeout": 5})


def test_cutover_without_reconciliation_is_rejected():
    from agents.search.administration import CatalogAdministration
    control = MemoryControl(generations=(GENERATION, "products-next"))
    control.records.pop("RECONCILIATION#products-next")
    admin = CatalogAdministration(control, Mock(), runtime_role="reader", writer_role="writer")
    with pytest.raises(ValueError, match="reconciliation"):
        admin.activate("products-next")
    admin.search.indices.update_aliases.assert_not_called()


def test_failed_never_served_rebuild_can_be_abandoned_without_deleting_evidence():
    from agents.search.administration import CatalogAdministration
    control = MemoryControl(generations=(GENERATION, "products-broken"), REBUILD={
        "generation": "products-broken", "complete": False, "cursor": {"product_id": {"S": "last"}},
    })
    admin = CatalogAdministration(control, Mock(), runtime_role="reader", writer_role="writer")
    assert admin.abort_rebuild("products-broken")["status"] == "rebuild_aborted_evidence_retained"
    assert control.get("REBUILD")["cursor"] == {"product_id": {"S": "last"}}
    assert control.get("REBUILD")["aborted"] is True
    assert control.get("PROJECTION")["generations"] == [GENERATION]
    admin.search.indices.delete.assert_not_called()
    with pytest.raises(ValueError, match="never-served"):
        admin.abort_rebuild(GENERATION)
