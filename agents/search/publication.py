"""Transactional canonical publication and a durable ordered outbox.

Each shard's sequence orders deliveries. Supplier source_revision
orders updates to one stable product ID. Neither depends on arrival timestamps.
"""

import time
import hashlib
from contextlib import contextmanager
from uuid import uuid4

from botocore.exceptions import ClientError

from .clients import attribute_map, native_map
from .contracts import CanonicalProduct
from .repository import native_numbers

OUTBOX_SHARDS = 16


def product_shard(product_id: str) -> int:
    return int.from_bytes(hashlib.sha256(product_id.encode("ascii")).digest()[:4], "big") % OUTBOX_SHARDS


def shard_key(prefix: str, shard: int) -> str:
    if type(shard) is not int or not 0 <= shard < OUTBOX_SHARDS:
        raise ValueError("Invalid publication shard")
    return f"{prefix}#{shard:02d}"


def outbox_partition(catalog_id: str, shard: int) -> str:
    return shard_key(catalog_id, shard)


def publication_locks() -> tuple[str, ...]:
    return tuple(shard_key("PROJECTION_LOCK", shard) for shard in range(OUTBOX_SHARDS))


def source_is_healthy(source: dict | None, *, now=None) -> bool:
    """Immutable imports and live feeds have explicitly different health evidence."""
    if not source or source.get("healthy") is not True:
        return False
    if source.get("mode") == "snapshot":
        return True
    checked = source.get("checked_at")
    return (
        source.get("mode") == "live" and type(checked) in (float, int)
        and 0 <= (time.time() if now is None else now) - checked <= 60
    )


def source_watermarks(control) -> dict[int, int]:
    return {shard: control.get(shard_key("SOURCE", shard))["sequence"] for shard in range(OUTBOX_SHARDS)}


class ControlStore:
    def __init__(self, client, table: str, catalog_id: str):
        self.client, self.table, self.catalog_id = client, table, catalog_id

    def get(self, key):
        response = self.client.get_item(
            TableName=self.table, Key=attribute_map({"pk": key}), ConsistentRead=True,
        )
        if "Item" not in response:
            return None
        item = native_numbers(native_map(response["Item"]))
        if item.get("pk") != key or item.get("catalog_id") != self.catalog_id:
            raise ValueError("Control record scope mismatch")
        return item["value"]

    def put(self, key, value, *, absent=False, lease=None):
        args = {"ConditionExpression": "attribute_not_exists(pk)"} if absent else {}
        put = {
            "TableName": self.table,
            "Item": attribute_map({"pk": key, "catalog_id": self.catalog_id, "value": value}), **args,
        }
        if lease is None:
            self.client.put_item(**put)
        else:
            self.client.transact_write_items(TransactItems=[
                {"ConditionCheck": {
                    "TableName": self.table, "Key": attribute_map({"pk": lease["key"]}),
                    "ConditionExpression": "#owner = :owner AND expires_at > :now",
                    "ExpressionAttributeNames": {"#owner": "owner"},
                    "ExpressionAttributeValues": attribute_map({":owner": lease["owner"], ":now": int(time.time())}),
                }}, {"Put": put},
            ])

    def transaction(self, records, *, lease, checks=()):
        """Fence an atomic checkpoint/configuration change against its lease."""
        self.client.transact_write_items(TransactItems=[
            {"ConditionCheck": {
                "TableName": self.table, "Key": attribute_map({"pk": lease["key"]}),
                "ConditionExpression": "#owner = :owner AND expires_at > :now",
                "ExpressionAttributeNames": {"#owner": "owner"},
                "ExpressionAttributeValues": attribute_map({":owner": lease["owner"], ":now": int(time.time())}),
            }},
            *checks,
            *[{"Put": {
                "TableName": self.table,
                "Item": attribute_map({"pk": key, "catalog_id": self.catalog_id, "value": value}),
            }} for key, value in records.items()],
        ])

    @contextmanager
    def lock(self, *, seconds=90, keys: tuple[str, ...] = ("PROJECTION_LOCK",)):
        if not keys or len(keys) > 20 or len(set(keys)) != len(keys):
            raise ValueError("Lease acquisition requires 1–20 distinct keys")
        owner = uuid4().hex
        now = int(time.time())
        self.client.transact_write_items(TransactItems=[{"Put": {
            "TableName": self.table,
            "Item": attribute_map({
                "pk": key, "owner": owner, "expires_at": now + seconds, "catalog_id": self.catalog_id,
            }),
            "ConditionExpression": "attribute_not_exists(pk) OR (catalog_id = :catalog AND expires_at < :now)",
            "ExpressionAttributeValues": attribute_map({":now": now, ":catalog": self.catalog_id}),
        }} for key in keys])
        try:
            yield {"key": keys[0], "owner": owner}
        finally:
            try:
                self.client.transact_write_items(TransactItems=[{"Delete": {
                    "TableName": self.table, "Key": attribute_map({"pk": key}),
                    "ConditionExpression": "#owner = :owner",
                    "ExpressionAttributeNames": {"#owner": "owner"},
                    "ExpressionAttributeValues": attribute_map({":owner": owner}),
                }} for key in keys])
            except ClientError as exc:
                # A replacement owner must retain its lease. Do not mask an
                # original failure merely because this invocation expired.
                if not lease_contention(exc):
                    raise


class CatalogPublisher:
    def __init__(self, client, *, products_table: str, outbox_table: str, control: ControlStore):
        self.client, self.products_table, self.outbox_table = client, products_table, outbox_table
        self.control = control

    def publish(self, product: CanonicalProduct) -> str:
        if product.catalog_id != self.control.catalog_id:
            raise ValueError("Publication belongs to another catalog")
        shard = product_shard(product.product_id)
        counter_key = shard_key("SOURCE", shard)
        for _ in range(4):
            response = self.client.get_item(
                TableName=self.products_table,
                Key=attribute_map({"product_id": product.product_id}), ConsistentRead=True,
            )
            existing = native_numbers(native_map(response["Item"])) if response.get("Item") else None
            if existing:
                previous = CanonicalProduct.model_validate(existing)
                if (previous.catalog_id, previous.product_id) != (product.catalog_id, product.product_id):
                    raise ValueError("Existing canonical identity differs from publication")
                if previous.source_revision > product.source_revision:
                    return "stale"
                if previous.source_revision == product.source_revision:
                    if previous.record_hash != product.record_hash:
                        raise ValueError("Same supplier revision has different source content")
                    return "duplicate"
            source = self.control.get(counter_key)
            if source is None:
                raise ValueError("Initialize the catalog before publishing products")
            sequence = source["sequence"] + 1
            event = {
                "catalog_id": product.catalog_id, "sequence": sequence,
                "catalog_shard": outbox_partition(product.catalog_id, shard),
                "event_id": f"{product.catalog_id}/{product.product_id}/{product.source_revision}",
                "accepted_at": time.time(), "product": product.model_dump(mode="json"),
                "previous_category": existing.get("category_id") if existing else None,
            }
            try:
                self.client.transact_write_items(
                    ClientRequestToken=uuid4().hex,
                    TransactItems=[
                        {"Put": {
                            "TableName": self.products_table, "Item": attribute_map(product.model_dump(mode="json")),
                            "ConditionExpression": "attribute_not_exists(product_id) OR source_revision < :revision",
                            "ExpressionAttributeValues": attribute_map({":revision": product.source_revision}),
                        }},
                        {"Put": {
                            "TableName": self.outbox_table, "Item": attribute_map(event),
                            "ConditionExpression": "attribute_not_exists(catalog_shard)",
                        }},
                        {"Update": {
                            "TableName": self.control.table, "Key": attribute_map({"pk": counter_key}),
                            "UpdateExpression": "SET #value.#sequence = :next",
                            "ConditionExpression": "#value.#sequence = :previous",
                            "ExpressionAttributeNames": {"#value": "value", "#sequence": "sequence"},
                            "ExpressionAttributeValues": attribute_map({
                                ":next": sequence, ":previous": source["sequence"],
                            }),
                        }},
                    ],
                )
                return "published"
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "TransactionCanceledException":
                    raise
                reasons = exc.response.get("CancellationReasons", [])
                if not reasons or any(
                    reason.get("Code") not in ("None", "ConditionalCheckFailed", "TransactionConflict")
                    for reason in reasons
                ):
                    raise
        raise RuntimeError("Concurrent publication exceeded the bounded retry limit")

    def set_source_health(self, healthy: bool, *, mode: str):
        if type(healthy) is not bool or mode not in ("snapshot", "live"):
            raise ValueError("Source health requires an explicit snapshot or live feed")
        self.client.update_item(
            TableName=self.control.table, Key=attribute_map({"pk": "SOURCE"}),
            UpdateExpression="SET #value.healthy = :healthy, #value.#mode = :mode, #value.checked_at = :now",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#value": "value", "#mode": "mode"},
            ExpressionAttributeValues=attribute_map({":healthy": healthy, ":mode": mode, ":now": time.time()}),
        )


class Outbox:
    def __init__(self, client, table, catalog_id):
        self.client, self.table, self.catalog_id = client, table, catalog_id

    def after(self, shard: int, sequence: int, *, limit=100) -> list[dict]:
        partition = outbox_partition(self.catalog_id, shard)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Outbox query is bounded at 100 events")
        response = self.client.query(
            TableName=self.table, ConsistentRead=True, Limit=limit,
            KeyConditionExpression="catalog_shard = :catalog AND #sequence > :sequence",
            ExpressionAttributeNames={"#sequence": "sequence"},
            ExpressionAttributeValues=attribute_map({
                ":catalog": partition, ":sequence": sequence,
            }),
            ScanIndexForward=True,
        )
        rows = [native_numbers(native_map(item)) for item in response.get("Items", [])]
        for offset, row in enumerate(rows, 1):
            if row.get("catalog_id") != self.catalog_id or row.get("catalog_shard") != partition or row.get("sequence") != sequence + offset:
                raise ValueError("Outbox contains a gap or unexpected catalog")
        return rows


def lease_contention(exc: ClientError) -> bool:
    reasons = exc.response.get("CancellationReasons", [])
    return (
        exc.response["Error"]["Code"] == "TransactionCanceledException" and bool(reasons)
        and all(reason.get("Code") in ("None", "ConditionalCheckFailed", "TransactionConflict") for reason in reasons)
    )
