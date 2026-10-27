"""IAM-only index initialization and resumable generation cutover.

The admin Lambda has the domain's master role. Runtime and projection roles
cannot invoke these control operations or mutate security roles/mappings.
"""

import time
import hashlib

from opensearchpy.exceptions import NotFoundError

from .catalog import alias_key, ingredient_key
from .clients import attribute_map
from .contracts import SearchConfiguration
from .opensearch_adapter import index_mapping
from .publication import OUTBOX_SHARDS, publication_locks, shard_key, source_is_healthy, source_watermarks

ADMIN_LOCKS = (*publication_locks(), "MAINTENANCE_LOCK")


class CatalogAdministration:
    def __init__(self, control, search, *, runtime_role: str, writer_role: str, maintenance_role: str | None = None):
        self.control, self.search = control, search
        self.runtime_role, self.writer_role = runtime_role, writer_role
        self.maintenance_role = maintenance_role

    def roles(self):
        definitions = {
            "product_reader": (self.runtime_role, [], ["indices:data/read/search*"]),
            "product_writer": (
                self.writer_role,
                ["cluster:monitor/health", "indices:data/write/bulk", "indices:data/read/mget"],
                ["indices:data/write/bulk*", "indices:data/write/index*", "indices:data/read/mget*",
                 "indices:data/read/get*", "indices:admin/refresh*"],
            ),
        }
        if self.maintenance_role:
            definitions["product_maintenance"] = (
                self.maintenance_role,
                ["cluster:monitor/health", "indices:data/write/bulk", "indices:data/read/mget"],
                ["indices:data/write/bulk*", "indices:data/write/index*", "indices:data/read/mget*",
                 "indices:data/read/get*", "indices:admin/refresh*", "indices:data/read/search*",
                 "indices:data/read/point_in_time/create", "indices:data/read/point_in_time/delete"],
            )
        for name, (role, cluster, actions) in definitions.items():
            for path, body in (
                (f"roles/{name}", {
                    "cluster_permissions": cluster,
                    "index_permissions": [{"index_patterns": ["products-*"], "allowed_actions": actions}],
                    "tenant_permissions": [],
                }),
                (f"rolesmapping/{name}", {"backend_roles": [role], "users": [], "hosts": []}),
            ):
                self.search.transport.perform_request(
                    "PUT", f"/_plugins/_security/api/{path}", body=body,
                    params={"request_timeout": 10},
                )

    def create_index(self, generation):
        mapping = index_mapping()
        try:
            actual = self.search.indices.get_mapping(index=generation, params={"request_timeout": 10})
        except NotFoundError:
            self.search.indices.create(
                index=generation,
                body={**mapping, "settings": {"number_of_shards": 2, "number_of_replicas": 1}},
                params={"request_timeout": 10},
            )
            return
        if actual.get(generation, {}).get("mappings") != mapping["mappings"]:
            raise ValueError("Existing generation has an incompatible mapping")

    def initialize(self, config: SearchConfiguration, registry):
        with self.control.lock(seconds=300, keys=ADMIN_LOCKS) as lease:
            self.roles()
            existing = self.control.get("CONFIG")
            if existing is not None:
                # A generation cutover legitimately changes these two identifiers.
                ignored = {"configuration_id", "index_generation"}
                actual = SearchConfiguration.model_validate(existing).model_dump(exclude=ignored)
                if actual != config.model_dump(exclude=ignored):
                    raise ValueError("Existing catalog requires an explicit migration")
                if any(
                    self.control.get(shard_key(prefix, shard)) is None
                    for prefix in ("SOURCE", "PROJECTION") for shard in range(OUTBOX_SHARDS)
                ):
                    raise ValueError("Existing publication layout requires an explicit migration")
                self.search.indices.update_aliases(body={"actions": [
                    {"add": {"index": existing["index_generation"], "alias": "products-current"}},
                ]}, params={"request_timeout": 10})
                return {"status": "already_initialized"}
            self.create_index(config.index_generation)
            for entry in registry.entries.values():
                self.control.put(ingredient_key(config.taxonomy_version, entry.ingredient_id), entry.model_dump(mode="json"))
            for name, ids in registry.aliases.items():
                self.control.put(alias_key(config.taxonomy_version, name), {
                    "normalized_name": name, "taxonomy_version": config.taxonomy_version,
                    "ingredient_ids": sorted(ids),
                })
            # CONFIG is written last; partial initialization can be replayed safely.
            self.control.put("SOURCE", {"mode": "snapshot", "healthy": False, "checked_at": time.time()}, lease=lease)
            self.control.put("PROJECTION", {"generations": [config.index_generation]}, lease=lease)
            for shard in range(OUTBOX_SHARDS):
                self.control.put(shard_key("SOURCE", shard), {"sequence": 0}, lease=lease)
                self.control.put(shard_key("PROJECTION", shard), {
                    "generations": {config.index_generation: {"sequence": 0, "error": None}},
                }, lease=lease)
            self.control.put(f"CONFIG_HISTORY#{config.index_generation}", config.model_dump(mode="json"))
            self.control.put(f"GENERATION#{config.index_generation}", {"created_at": time.time()}, lease=lease)
            self.control.put("CONFIG", config.model_dump(mode="json"), absent=True)
            self.search.indices.update_aliases(body={"actions": [
                {"add": {"index": config.index_generation, "alias": "products-current"}},
            ]}, params={"request_timeout": 10})
            return {"status": "initialized"}

    def start_rebuild(self, generation: str):
        with self.control.lock(keys=ADMIN_LOCKS) as lease:
            config = SearchConfiguration.model_validate(self.control.get("CONFIG"))
            updated = SearchConfiguration.model_validate({
                **config.model_dump(), "index_generation": generation,
            })
            if not generation.startswith("products-"):
                raise ValueError("Generation names must start with products-")
            progress = self.control.get("PROJECTION")
            if generation in progress["generations"] or self.control.get(f"GENERATION#{generation}") is not None:
                raise ValueError("Generation identity already exists; resume it or use a new generation name")
            if len(progress["generations"]) >= 3:
                raise ValueError("Retire an old generation before starting another rebuild")
            existing = self.control.get("REBUILD")
            if existing and not existing["complete"] and not existing.get("aborted"):
                raise ValueError("Another rebuild is in progress")
            self.create_index(updated.index_generation)
            rebuild = {
                "generation": generation, "cursor": None, "complete": False,
                "started_at": time.time(), "start_watermarks": source_watermarks(self.control),
            }
            # Updates are mirrored to the new index while its resumable scan runs.
            progress = {
                **progress, "generations": [*progress["generations"], generation],
            }
            records = {
                "REBUILD": rebuild, "PROJECTION": progress,
                f"GENERATION#{generation}": {"created_at": time.time()},
            }
            for shard, watermark in rebuild["start_watermarks"].items():
                key = shard_key("PROJECTION", shard)
                state = self.control.get(key)
                records[key] = {"generations": {
                    **state["generations"], generation: {"sequence": watermark, "error": None},
                }}
            # Integer keys are serialized as strings at this metadata boundary.
            rebuild["start_watermarks"] = {str(key): value for key, value in rebuild["start_watermarks"].items()}
            self.control.transaction(records, lease=lease)
            return {"status": "backfill_started", "generation": generation}

    def activate(self, generation: str):
        """Switch only a fully backfilled retained generation at a checked watermark."""
        with self.control.lock(keys=ADMIN_LOCKS) as lease:
            config = SearchConfiguration.model_validate(self.control.get("CONFIG"))
            progress, source = self.control.get("PROJECTION"), self.control.get("SOURCE")
            rebuild = self.control.get("REBUILD")
            if generation not in progress["generations"] or not source_is_healthy(source):
                raise ValueError("Generation is not caught up to a healthy source")
            if rebuild and generation == rebuild["generation"] and not rebuild["complete"]:
                raise ValueError("Backfill is incomplete")
            watermarks = source_watermarks(self.control)
            for shard, watermark in watermarks.items():
                state = self.control.get(shard_key("PROJECTION", shard))["generations"][generation]
                if state["sequence"] != watermark or state["error"]:
                    raise ValueError("Generation is not caught up to a healthy source")
            reconciliation = self.control.get(f"RECONCILIATION#{generation}")
            if (
                not reconciliation or reconciliation.get("status") != "complete"
                or time.time() - reconciliation["completed_at"] > 86400
                or reconciliation.get("error")
            ):
                raise ValueError("Generation requires a successful, recent reconciliation")
            self.search.indices.refresh(index=generation, params={"request_timeout": 10})
            health = self.search.cluster.health(index=generation, params={"request_timeout": 10})
            if health.get("status") not in ("green", "yellow") or health.get("timed_out") is not False:
                raise ValueError("Target generation is not healthy")
            historical = self.control.get(f"CONFIG_HISTORY#{generation}")
            new_config = SearchConfiguration.model_validate(historical or {
                **config.model_dump(), "index_generation": generation,
                "configuration_id": "exact-" + hashlib.sha256(generation.encode()).hexdigest()[:24],
            })
            # Runtime pins physical generations from CONFIG. The operational alias
            # may switch first; it cannot expose unapproved runtime configuration.
            self.search.indices.update_aliases(body={"actions": [
                {"remove": {"index": "products-*", "alias": "products-current"}},
                {"add": {"index": generation, "alias": "products-current"}},
            ]}, params={"request_timeout": 10})
            ready = {
                "catalog_id": config.catalog_id, "configuration_id": new_config.configuration_id,
                "index_generation": generation, "healthy": True, "source_healthy": True,
                "checked_at": time.time(), "oldest_pending_at": None,
            }
            # These checks fence concurrent supplier publications, not just
            # projection writers. A changed source retries promotion safely.
            checks = [{"ConditionCheck": {
                "TableName": self.control.table, "Key": attribute_map({"pk": shard_key("SOURCE", shard)}),
                "ConditionExpression": "#value.#sequence = :sequence",
                "ExpressionAttributeNames": {"#value": "value", "#sequence": "sequence"},
                "ExpressionAttributeValues": attribute_map({":sequence": watermark}),
            }} for shard, watermark in watermarks.items()]
            checks.append({"ConditionCheck": {
                    "TableName": self.control.table, "Key": attribute_map({"pk": "SOURCE"}),
                    "ConditionExpression": "#value = :source",
                    "ExpressionAttributeNames": {"#value": "value"},
                    "ExpressionAttributeValues": attribute_map({":source": source}),
                }})
            records = {
                "CONFIG": new_config.model_dump(mode="json"),
                f"CONFIG_HISTORY#{generation}": new_config.model_dump(mode="json"),
                f"READINESS#{generation}": ready,
            }
            if generation != config.index_generation:
                records["LAST_CUTOVER"] = {"at": time.time(), "previous": config.index_generation}
            self.control.transaction(records, lease=lease, checks=checks)
            return {"status": "activated", "generation": generation}

    def retire(self, generation: str):
        """Stop mirroring after old routines expire; retain index and outbox for recovery."""
        with self.control.lock(keys=ADMIN_LOCKS) as lease:
            config, cutover = self.control.get("CONFIG"), self.control.get("LAST_CUTOVER")
            rebuild = self.control.get("REBUILD")
            if (
                generation == config["index_generation"] or not cutover
                or time.time() - cutover["at"] < 7 * 86400
                or (rebuild and generation == rebuild["generation"] and not rebuild["complete"])
            ):
                raise ValueError("Generation is active, building, or still within the retention grace period")
            progress = self.control.get("PROJECTION")
            records = {"PROJECTION": {
                **progress, "generations": [item for item in progress["generations"] if item != generation],
            }}
            for shard in range(OUTBOX_SHARDS):
                key = shard_key("PROJECTION", shard)
                state = self.control.get(key)
                records[key] = {"generations": {name: value for name, value in state["generations"].items() if name != generation}}
            self.control.transaction(records, lease=lease)
            return {"status": "retained_without_updates", "generation": generation}

    def abort_rebuild(self, generation: str):
        """Abandon an unserved rebuild without deleting any recovery evidence."""
        with self.control.lock(keys=ADMIN_LOCKS) as lease:
            rebuild = self.control.get("REBUILD")
            if (
                not rebuild or rebuild["generation"] != generation
                or self.control.get(f"CONFIG_HISTORY#{generation}") is not None
                or self.control.get("CONFIG")["index_generation"] == generation
            ):
                raise ValueError("Only the current, never-served rebuild can be abandoned")
            progress = self.control.get("PROJECTION")
            records = {
                "REBUILD": {**rebuild, "aborted": True, "aborted_at": time.time()},
                "PROJECTION": {"generations": [name for name in progress["generations"] if name != generation]},
            }
            for shard in range(OUTBOX_SHARDS):
                key = shard_key("PROJECTION", shard)
                state = self.control.get(key)
                records[key] = {"generations": {name: value for name, value in state["generations"].items() if name != generation}}
            self.control.transaction(records, lease=lease)
            return {"status": "rebuild_aborted_evidence_retained", "generation": generation}
