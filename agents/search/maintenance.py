"""Resumable catalog maintenance, outside the application request path.

Scans and PIT pagination belong exclusively to this background role. Every page
is replayable; checkpoints are fenced by a lease. No operation hard-deletes a
product, tombstone, index or outbox event.
"""

import time

from opensearchpy.exceptions import NotFoundError

from .catalog import IngredientEntry, ingredient_key, summary_key
from .clients import attribute_map, native_map
from .contracts import CanonicalProduct, SearchConfiguration
from .errors import CatalogIntegrityError
from .opensearch_adapter import OpenSearchExactAdapter, document_id, search_document
from .publication import OUTBOX_SHARDS, publication_locks, shard_key, source_is_healthy, source_watermarks
from .repository import native_numbers


class CatalogMaintenance:
    def __init__(self, control, outbox, writer, *, products_table):
        self.control, self.outbox, self.writer = control, outbox, writer
        self.search, self.products_table = writer.client, products_table

    def _scan(self, cursor=None):
        response = self.control.client.scan(
            TableName=self.products_table, Limit=100, ConsistentRead=True,
            **({"ExclusiveStartKey": cursor} if cursor else {}),
        )
        products = tuple(CanonicalProduct.model_validate(native_numbers(native_map(item))) for item in response["Items"])
        if len(products) > 100 or any(product.catalog_id != self.control.catalog_id for product in products):
            raise CatalogIntegrityError("Canonical scan contains an invalid catalog or page")
        return products, response.get("LastEvaluatedKey")

    def _pit(self, generation):
        response = self.search.create_pit(index=generation, params={
            "keep_alive": "10m", "allow_partial_pit_creation": "false", "request_timeout": 10,
        })
        shards = response.get("_shards", {})
        if (
            not isinstance(response.get("pit_id"), str) or not response["pit_id"]
            or type(shards.get("total")) is not int or shards["total"] < 1
            or shards.get("successful") != shards["total"] or shards.get("failed") != 0
        ):
            raise RuntimeError("Incomplete maintenance snapshot")
        return response["pit_id"]

    def _search(self, body):
        response = self.search.search(body={**body, "timeout": "10s"}, params={
            "request_timeout": 12, "allow_partial_search_results": "false",
        })
        OpenSearchExactAdapter._validate_complete(response)
        return response

    def _close(self, pit):
        if pit:
            self.search.delete_pit(body={"pit_id": [pit]}, params={"request_timeout": 5})

    def backfill_page(self, lease):
        state = self.control.get("REBUILD")
        if not state or state["complete"] or state.get("aborted"):
            return
        products, cursor = self._scan(state.get("cursor"))
        self.writer.write(state["generation"], products)
        if not cursor:
            self.search.indices.refresh(index=state["generation"], params={"request_timeout": 5})
        self.control.put("REBUILD", {
            **state, "cursor": cursor, "complete": not bool(cursor), "error": None,
        }, lease=lease)

    def reconcile_page(self, generation, lease):
        key = f"RECONCILIATION#{generation}"
        state = self.control.get(key) or {}
        rebuild = self.control.get("REBUILD")
        if rebuild and rebuild["generation"] == generation and not rebuild["complete"]:
            return
        if state.get("status") == "quarantined":
            return  # A fresh generation is required; never overwrite equal revisions.
        if state.get("status") == "complete" and time.time() - state["completed_at"] < 12 * 3600:
            return
        if not state or state.get("status") == "complete":
            state = {
                "status": "running", "phase": "canonical", "cursor": None, "checked": 0,
                "started_at": time.time(), "completed_at": state.get("completed_at"),
                "watermarks": {str(key): value for key, value in source_watermarks(self.control).items()},
            }
        try:
            if state["phase"] == "canonical":
                products, cursor = self._scan(state.get("cursor"))
                # Replaying every full revision repairs missing/older projections
                # and validates equal-version bodies, including tombstones.
                self.writer.write(generation, products)
                state.update(cursor=cursor, checked=state["checked"] + len(products))
                if not cursor:
                    self.search.indices.refresh(index=generation, params={"request_timeout": 5})
                    state.update(phase="index", pit=None)
            else:
                if not state.get("pit"):
                    state.update(pit=self._pit(generation), cursor=None)
                body = {
                    "size": 100, "track_total_hits": False, "version": True,
                    "pit": {"id": state["pit"], "keep_alive": "10m"},
                    "query": {"match_all": {}},
                    "sort": [{"product_id": "asc"}],
                }
                if state.get("cursor"):
                    body["search_after"] = state["cursor"]
                response = self._search(body)
                state["pit"] = response.get("pit_id", state["pit"])
                hits = response["hits"]["hits"]
                self._verify_index_page(generation, hits, state.get("cursor"))
                if hits:
                    state["cursor"] = hits[-1]["sort"]
                else:
                    self._close(state["pit"])
                    state.update(status="complete", completed_at=time.time(), pit=None, cursor=None)
            state["error"] = None
        except NotFoundError:
            # Lost/expired PIT is not an integrity verdict. Recheck the entire
            # index side using a new snapshot; no page can be silently skipped.
            state.update(pit=None, cursor=None, error="Snapshot expired; retrying")
        except CatalogIntegrityError as exc:
            state.update(status="quarantined", error=str(exc), failed_at=time.time())
        except Exception as exc:
            state.update(error=type(exc).__name__, failed_at=time.time())
            self.control.put(key, state, lease=lease)
            raise
        self.control.put(key, state, lease=lease)

    def _verify_index_page(self, generation, hits, cursor=None):
        if not isinstance(hits, list) or len(hits) > 100:
            raise CatalogIntegrityError("Invalid reconciliation page")
        previous = cursor[0] if cursor else ""
        products = []
        for hit in hits:
            source = hit.get("_source", {})
            identifier = source.get("product_id")
            if (
                not isinstance(identifier, str) or identifier <= previous
                or hit.get("sort") != [identifier] or hit.get("_index") != generation
                or source.get("catalog_id") != self.control.catalog_id
                or hit.get("_id") != document_id(self.control.catalog_id, identifier)
                or type(source.get("source_revision")) is not int
                or hit.get("_version") != source["source_revision"]
            ):
                raise CatalogIntegrityError("Index identity, revision or page order differs")
            previous = identifier
            # Read after observing the projection. Canonical revisions cannot be
            # behind an acknowledged projection from the publication protocol.
            response = self.control.client.get_item(
                TableName=self.products_table, Key=attribute_map({"product_id": identifier}), ConsistentRead=True,
            )
            if "Item" not in response:
                raise CatalogIntegrityError(f"Index product has no canonical identity: {identifier}")
            canonical = CanonicalProduct.model_validate(native_numbers(native_map(response["Item"])))
            if (
                canonical.catalog_id != self.control.catalog_id or canonical.product_id != identifier
                or canonical.source_revision < source["source_revision"]
                or (canonical.source_revision == source["source_revision"] and source != search_document(canonical))
            ):
                raise CatalogIntegrityError(f"Index facts differ at canonical revision: {identifier}")
            if canonical.source_revision > source["source_revision"]:
                products.append(canonical)
        self.writer.write(generation, tuple(products))

    def summary_page(self, config, lease):
        key = "SUMMARY_BUILD"
        state = self.control.get(key)
        if state and state.get("generation") != config.index_generation:
            self._close(state.get("pit"))
            state = None
        if state and state.get("complete") and time.time() - state["as_of"] < 180:
            return
        if not state or state.get("complete"):
            state = {
                "generation": config.index_generation, "as_of": time.time(),
                "pit": self._pit(config.index_generation), "after": None,
                "top": {category: [] for category in config.categories}, "complete": False,
            }
        composite = {
            "size": 500,
            "sources": [
                {"category": {"terms": {"field": "category_id", "order": "asc"}}},
                {"ingredient": {"terms": {"field": "ingredient_ids", "order": "asc"}}},
            ],
        }
        if state["after"]:
            composite["after"] = state["after"]
        try:
            result = self._search({
                # Count all matching documents in this background snapshot.
                # With size=0/track_total_hits=false, the tested engine reports
                # terminated_early=true; retain the strict completion check.
                "size": 0, "track_total_hits": True,
                "pit": {"id": state["pit"], "keep_alive": "10m"},
                "query": {"bool": {"filter": [
                    {"term": {"catalog_id": config.catalog_id}},
                    {"term": {"taxonomy_version": config.taxonomy_version}},
                    {"term": {"schema_version": config.schema_version}},
                    {"term": {"active": True}}, {"term": {"is_deleted": False}},
                ]}},
                "aggs": {"ingredients": {"composite": composite}},
            })
            state["pit"] = result.get("pit_id", state["pit"])
            response = result["aggregations"]["ingredients"]
        except NotFoundError:
            self.control.put(key, {**state, "complete": True, "as_of": 0, "pit": None}, lease=lease)
            return
        buckets = response["buckets"]
        if not isinstance(buckets, list) or len(buckets) > 500:
            raise RuntimeError("Invalid ingredient aggregation")
        previous = tuple(state["after"][part] for part in ("category", "ingredient")) if state["after"] else None
        for bucket in buckets:
            category, identifier = bucket["key"]["category"], bucket["key"]["ingredient"]
            current = (category, identifier)
            if (
                category not in state["top"] or not isinstance(identifier, str)
                or type(bucket["doc_count"]) is not int or bucket["doc_count"] <= 0
                or (previous is not None and current <= previous)
            ):
                raise RuntimeError("Invalid ingredient aggregation bucket")
            previous = current
            entries = [*state["top"][category], {"ingredient_id": identifier, "count": bucket["doc_count"]}]
            state["top"][category] = sorted(entries, key=lambda item: (-item["count"], item["ingredient_id"]))[:30]
        after = response.get("after_key")
        if buckets and (not after or after == state["after"]):
            raise RuntimeError("Ingredient aggregation did not advance its cursor")
        state["after"] = after
        if not buckets:
            records = {}
            for category, entries in state["top"].items():
                ingredients = []
                for entry in entries:
                    resolved = IngredientEntry.model_validate(self.control.get(ingredient_key(config.taxonomy_version, entry["ingredient_id"])))
                    if resolved.ingredient_id != entry["ingredient_id"] or resolved.taxonomy_version != config.taxonomy_version:
                        raise CatalogIntegrityError("Summary ingredient identity differs")
                    ingredients.append({**entry, "display_name": resolved.display_name})
                records[summary_key(config.taxonomy_version, category)] = {
                    "category_id": category, "taxonomy_version": config.taxonomy_version,
                    "index_generation": config.index_generation, "as_of": state["as_of"], "ingredients": ingredients,
                }
            self._close(state["pit"])
            state.update(complete=True, pit=None)
            # Summary publication and its completion marker commit together.
            self.control.transaction({**records, key: state}, lease=lease)
        else:
            self.control.put(key, state, lease=lease)

    def heartbeat(self):
        # All shard leases prevent a newer error/checkpoint from racing this
        # readiness snapshot. Health reads do not lock long-running backfills.
        with self.control.lock(seconds=90, keys=publication_locks()) as lease:
            config = SearchConfiguration.model_validate(self.control.get("CONFIG"))
            source = self.control.get("SOURCE")
            watermarks = source_watermarks(self.control)
            states = [self.control.get(shard_key("PROJECTION", shard)) for shard in range(OUTBOX_SHARDS)]
            results = {}
            for generation in self.control.get("PROJECTION")["generations"]:
                historical = self.control.get(f"CONFIG_HISTORY#{generation}")
                if not historical:
                    continue
                pending, failures = [], []
                for shard, state in enumerate(states):
                    ack = state["generations"][generation]
                    if ack["error"]:
                        failures.append(ack["error"])
                    if ack["sequence"] > watermarks[shard]:
                        failures.append("Checkpoint ahead of source")
                    elif ack["sequence"] < watermarks[shard]:
                        try:
                            rows = self.outbox.after(shard, ack["sequence"], limit=1)
                            if not rows or type(rows[0].get("accepted_at")) not in (int, float):
                                failures.append("Source capture gap")
                            else:
                                pending.append(rows[0]["accepted_at"])
                        except Exception as exc:
                            failures.append(type(exc).__name__)
                reconciled = self.control.get(f"RECONCILIATION#{generation}") or {}
                if (
                    reconciled.get("error") or not reconciled.get("completed_at")
                    or time.time() - reconciled["completed_at"] > 86400
                ):
                    failures.append("Reconciliation is missing, failed or overdue")
                try:
                    health = self.search.cluster.health(index=generation, params={"request_timeout": 5})
                except Exception as exc:
                    failures.append(type(exc).__name__)
                    health = {}
                oldest = min(pending) if pending else None
                ready = {
                    "catalog_id": config.catalog_id, "configuration_id": historical["configuration_id"],
                    "index_generation": generation,
                    "healthy": not failures and health.get("status") in ("green", "yellow") and health.get("timed_out") is False,
                    "source_healthy": source_is_healthy(source), "checked_at": time.time(),
                    "oldest_pending_at": oldest,
                }
                self.control.put(f"READINESS#{generation}", ready, lease=lease)
                results[generation] = {
                    "lag_seconds": max(0, time.time() - oldest) if oldest is not None else 0,
                    "healthy": ready["healthy"], "source_healthy": ready["source_healthy"],
                    "reconciliation_age_seconds": time.time() - reconciled.get("completed_at", 0) if reconciled.get("completed_at") else 86401,
                }
            return results

    def run(self, *, seconds=8):
        with self.control.lock(seconds=120, keys=("MAINTENANCE_LOCK",)) as lease:
            deadline = time.monotonic() + seconds
            config = SearchConfiguration.model_validate(self.control.get("CONFIG"))
            jobs = [("REBUILD", self.backfill_page), ("SUMMARY_BUILD", lambda lease: self.summary_page(config, lease))]
            jobs.extend((f"RECONCILIATION#{generation}", lambda lease, generation=generation: self.reconcile_page(generation, lease))
                        for generation in self.control.get("PROJECTION")["generations"])
            cursor = (self.control.get("MAINTENANCE_CURSOR") or {}).get("next", 0)
            while time.monotonic() < deadline:
                key, operation = jobs[cursor % len(jobs)]
                cursor += 1
                try:
                    if (self.control.get(key) or {}).get("retry_after", 0) <= time.time():
                        operation(lease)
                except Exception as exc:
                    # Bounded retry by the next scheduled invocation; preserve
                    # the page and expose the failure instead of busy-looping.
                    state = self.control.get(key) or {}
                    self.control.put(key, {**state, "error": type(exc).__name__, "failed_at": time.time(), "retry_after": time.time() + 30}, lease=lease)
                    self.control.put("MAINTENANCE_CURSOR", {"next": cursor}, lease=lease)
                    raise
                self.control.put("MAINTENANCE_CURSOR", {"next": cursor}, lease=lease)
                if cursor % len(jobs) == 0:
                    break
