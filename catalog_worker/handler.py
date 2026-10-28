"""Private worker/admin Lambda entrypoints; all product changes use the outbox."""

import json
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from agents.search.administration import CatalogAdministration
from agents.search.clients import dynamodb_resource, search_client
from agents.search.contracts import SearchConfiguration
from agents.search.normalization import IngredientRegistry
from agents.search.maintenance import CatalogMaintenance
from agents.search.projection import ProjectionWorker, ProjectionWriter
from agents.search.publication import ControlStore, Outbox, OUTBOX_SHARDS, lease_contention, outbox_partition, source_watermarks, shard_key
from agents.telemetry import emit_metrics


def components():
    session = boto3.Session()
    client = dynamodb_resource(session, background=True).client
    control = ControlStore(client, os.environ["CATALOG_METADATA_TABLE_NAME"], os.environ["CATALOG_ID"])
    search = search_client(os.environ["OPENSEARCH_ENDPOINT"], session)
    return control, search


def worker(event, context):
    control, search = components()
    # CONFIG is published last by initialization. Scheduled invocations can
    # arrive before that step, and must not compete for its projection leases.
    if control.get("CONFIG") is None:
        return {"status": "not_initialized"}
    projection = ProjectionWorker(
        control, Outbox(control.client, os.environ["CATALOG_OUTBOX_TABLE_NAME"], control.catalog_id),
        ProjectionWriter(search), products_table=os.environ["PRODUCTS_TABLE_NAME"],
    )
    if "shard" in event:
        shards = [event["shard"]]
        if type(shards[0]) is not int or not 0 <= shards[0] < OUTBOX_SHARDS:
            raise ValueError("Invalid worker shard")
    else:
        partitions = {outbox_partition(control.catalog_id, shard): shard for shard in range(OUTBOX_SHARDS)}
        shards = sorted({partitions[record["dynamodb"]["Keys"]["catalog_shard"]["S"]] for record in event["Records"]})
    results = []
    for shard in shards:
        try:
            result = projection.run(shard, seconds=min(45, max(1, context.get_remaining_time_in_millis() / 1000 - 20)))
            print(json.dumps({"event": "catalog_projection", "shard": shard, "failures": len(result["failures"])}))
            emit_metrics("catalog_projection", {"ProjectionFailures": (len(result["failures"]), "Count")}, shard=shard)
            results.append(result)
        except ClientError as exc:
            if not lease_contention(exc):
                raise
            results.append({"shard": shard, "status": "leased"})
    return results


def maintenance(event, context):
    control, search = components()
    if control.get("CONFIG") is None:
        return {"status": "not_initialized"}
    job = CatalogMaintenance(
        control, Outbox(control.client, os.environ["CATALOG_OUTBOX_TABLE_NAME"], control.catalog_id),
        ProjectionWriter(search), products_table=os.environ["PRODUCTS_TABLE_NAME"],
    )
    # Readiness within 60 seconds even for idle catalogs. Stream workers provide
    # low-latency projection; this minute schedule also recovers missed signals.
    deadline = time.monotonic() + min(45, max(1, context.get_remaining_time_in_millis() / 1000 - 30))
    next_heartbeat = 0
    while time.monotonic() < deadline:
        try:
            if time.monotonic() >= next_heartbeat:
                for generation, metrics in job.heartbeat().items():
                    print(json.dumps({"event": "catalog_health", "generation": generation, **metrics}))
                    emit_metrics("catalog_health", {
                        "PublicationLag": (metrics["lag_seconds"], "Seconds"),
                        "ReconciliationAge": (metrics["reconciliation_age_seconds"], "Seconds"),
                        "UnhealthyGeneration": (int(not metrics["healthy"] or not metrics["source_healthy"]), "Count"),
                    }, generation=generation)
                next_heartbeat = time.monotonic() + 10
            job.run(seconds=min(8, max(1, deadline - time.monotonic())))
        except ClientError as exc:
            if not lease_contention(exc):
                raise
        except Exception as exc:
            print(json.dumps({"event": "catalog_maintenance_failure", "error": type(exc).__name__, "failures": 1}))
            emit_metrics("catalog_maintenance_failure", {"MaintenanceFailures": (1, "Count")})
        time.sleep(0.25)
    return {"status": "maintenance_tick_complete"}


def admin(event, context):
    if not isinstance(event, dict) or set(event) - {"action", "generation"}:
        raise ValueError("Invalid catalog administration request")
    control, search = components()
    administration = CatalogAdministration(
        control, search, runtime_role=os.environ["SEARCH_RUNTIME_ROLE_ARN"],
        writer_role=os.environ["SEARCH_WRITER_ROLE_ARN"],
        maintenance_role=os.environ["SEARCH_MAINTENANCE_ROLE_ARN"],
    )
    action = event.get("action")
    if action == "initialize":
        config = SearchConfiguration.model_validate_json(Path("data/search-config.json").read_text())
        registry = IngredientRegistry(json.loads(Path("data/ingredient-registry.json").read_text()), config.taxonomy_version)
        # Initialization is replayable, including on an existing catalog. Wait
        # briefly for ordinary worker leases; never remove another owner's lock.
        deadline = time.monotonic() + min(
            60, max(0, context.get_remaining_time_in_millis() / 1000 - 10),
        )
        while True:
            try:
                return administration.initialize(config, registry)
            except ClientError as exc:
                if not lease_contention(exc):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(1, remaining))
    if action == "status":
        return {
            **{key: control.get(key) for key in ("CONFIG", "SOURCE", "PROJECTION", "REBUILD")},
            "source_watermarks": source_watermarks(control),
            "shards": {shard: control.get(shard_key("PROJECTION", shard)) for shard in range(OUTBOX_SHARDS)},
        }
    if action in ("start_rebuild", "activate", "retire", "abort_rebuild"):
        generation = event.get("generation")
        if not isinstance(generation, str):
            raise ValueError("A generation is required")
        return getattr(administration, action)(generation)
    raise ValueError("Unknown catalog administration action")
