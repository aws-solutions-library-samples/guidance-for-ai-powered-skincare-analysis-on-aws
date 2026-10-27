"""Replay full external-version documents, including retained tombstones."""

import json
import time

from .contracts import CanonicalProduct
from .errors import CatalogIntegrityError
from .opensearch_adapter import document_id, search_document
from .publication import product_shard, shard_key


class ProjectionWriter:
    def __init__(self, client):
        self.client = client

    def write(self, generation: str, products: tuple[CanonicalProduct, ...]):
        if not products:
            return
        if len(products) > 100:
            raise ValueError("Projection batches are bounded at 100")
        lines = []
        for product in products:
            lines.extend((
                json.dumps({"index": {
                    "_index": generation, "_id": document_id(product.catalog_id, product.product_id),
                    "version": product.source_revision, "version_type": "external",
                }}),
                json.dumps(search_document(product)),
            ))
        response = self.client.bulk(body="\n".join(lines) + "\n", params={"request_timeout": 5})
        items = response.get("items")
        if not isinstance(items, list) or len(items) != len(products) or type(response.get("errors")) is not bool:
            raise RuntimeError("Projection bulk response is incomplete")
        conflicts = []
        for product, item in zip(products, items, strict=True):
            if not isinstance(item, dict) or set(item) != {"index"} or not isinstance(item["index"], dict):
                raise RuntimeError("Projection bulk item is malformed")
            result = item["index"]
            identifier = document_id(product.catalog_id, product.product_id)
            if result.get("_id") != identifier or result.get("_index") != generation:
                raise RuntimeError("Projection response identity differs")
            if result.get("status") in (200, 201):
                if result.get("_version") != product.source_revision:
                    raise RuntimeError("Projection accepted an unexpected version")
                continue
            if result.get("status") != 409:
                raise RuntimeError("Projection item failed")
            conflicts.append(product)
        if response["errors"] != bool(conflicts):
            raise RuntimeError("Projection bulk error summary differs from its items")
        if not conflicts:
            return
        response = self.client.mget(
            index=generation,
            body={"ids": [document_id(product.catalog_id, product.product_id) for product in conflicts]},
            params={"request_timeout": 5},
        )
        documents = response.get("docs", [])
        if len(documents) != len(conflicts):
            raise RuntimeError("Projection conflict validation is incomplete")
        for product, current in zip(conflicts, documents, strict=True):
            identifier = document_id(product.catalog_id, product.product_id)
            source = current.get("_source", {})
            revision = source.get("source_revision")
            if (
                current.get("_id") != identifier or current.get("_index") != generation
                or current.get("found") is not True or type(revision) is not int
                or current.get("_version") != revision
                or source.get("catalog_id") != product.catalog_id
                or source.get("product_id") != product.product_id
                or revision < product.source_revision
                or (revision == product.source_revision and source != search_document(product))
            ):
                raise CatalogIntegrityError("External-version conflict has inconsistent source content")


class ProjectionWorker:
    def __init__(self, control, outbox, writer, *, products_table: str):
        self.control, self.outbox, self.writer = control, outbox, writer
        self.products_table = products_table

    def run(self, shard: int, *, seconds=45):
        key = shard_key("PROJECTION", shard)
        with self.control.lock(seconds=150, keys=(shard_key("PROJECTION_LOCK", shard),)) as lease:
            started = time.monotonic()
            generations = self.control.get("PROJECTION")["generations"]
            progress = self.control.get(key)
            failures = {}
            # Round-robin batches: a slow/broken retained generation cannot hold
            # successful generations' acknowledgements hostage.
            while time.monotonic() - started < seconds:
                worked = False
                for generation in generations:
                    if generation in failures:
                        continue
                    state = progress["generations"][generation]
                    rows = []
                    try:
                        rows = self.outbox.after(shard, state["sequence"])
                        source = self.control.get(shard_key("SOURCE", shard))
                        if state["sequence"] > source["sequence"] or (not rows and state["sequence"] < source["sequence"]):
                            raise RuntimeError("Source and outbox checkpoints disagree")
                        if not rows:
                            continue
                        products = tuple(CanonicalProduct.model_validate(row["product"]) for row in rows)
                        if any(
                            product.catalog_id != self.control.catalog_id or product_shard(product.product_id) != shard
                            or row["event_id"] != f"{product.catalog_id}/{product.product_id}/{product.source_revision}"
                            for row, product in zip(rows, products, strict=True)
                        ):
                            raise ValueError("Outbox event identity differs from its canonical product")
                        self.writer.write(generation, products)
                        self.writer.client.indices.refresh(index=generation, params={"request_timeout": 5})
                        state = {"sequence": rows[-1]["sequence"], "error": None}
                        worked = True
                    except Exception as exc:
                        # Keep the poison event pending and retain one bounded
                        # diagnostic per shard/generation. Replay clears only
                        # this generation's error after a verified write.
                        failures[generation] = type(exc).__name__
                        state = {**state, "error": {
                            "at": time.time(), "type": type(exc).__name__,
                            "sequence": state["sequence"] + 1,
                            "event_ids": [row.get("event_id") for row in rows][:100],
                        }}
                        ready = self.control.get(f"READINESS#{generation}")
                        if ready:
                            self.control.put(f"READINESS#{generation}", {
                                **ready, "healthy": False, "checked_at": time.time(),
                            }, lease=lease)
                    progress["generations"][generation] = state
                    self.control.put(key, progress, lease=lease)
                if not worked:
                    break
            return {"shard": shard, "generations": progress["generations"], "failures": failures}
