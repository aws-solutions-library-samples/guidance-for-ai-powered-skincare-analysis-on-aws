"""Supplier facts and reviewed identity aliases; no runtime chemical inference."""

from datetime import UTC, datetime

from .catalog import IngredientEntry, normalize_name
from .contracts import CanonicalProduct, SearchConfiguration, matching_hash, record_hash


class IngredientRegistry:
    def __init__(self, entries: list[dict], version: str):
        self.entries = {}
        self.aliases = {}
        for raw in entries:
            entry = IngredientEntry.model_validate(raw)
            if entry.taxonomy_version != version or entry.ingredient_id in self.entries:
                raise ValueError("Duplicate registry ID or mismatched taxonomy version")
            self.entries[entry.ingredient_id] = entry
            for name in (entry.display_name, *entry.aliases):
                self.aliases.setdefault(normalize_name(name), set()).add(entry.ingredient_id)

    def resolve(self, names: list[str]) -> tuple[list[str], list[str]]:
        ids, unresolved = set(), []
        for name in names:
            matches = self.aliases.get(normalize_name(name), set())
            if len(matches) == 1:
                ids.update(matches)
            else:
                unresolved.append(name)
        return sorted(ids), unresolved


def normalize_product(
    values: dict, registry: IngredientRegistry, config: SearchConfiguration, *, now: str | None = None,
) -> CanonicalProduct:
    """Input contains explicit supplier IDs/revisions; unknown eligibility stays unknown."""
    now = now or datetime.now(UTC).isoformat()
    raw = values.get("raw_ingredients", [])
    if not isinstance(raw, list) or len(raw) > 512:
        raise ValueError("Ingredients must be a bounded list")
    ids, unresolved = registry.resolve(raw)
    body = {
        "brand": "", "image_path": "", "price_minor": None, "currency": None,
        "market_ids": [], "availability": "unknown",
        "ingredient_list_complete": False,
        **values,
        "catalog_id": config.catalog_id, "schema_version": config.schema_version,
        "taxonomy_version": config.taxonomy_version, "ingested_at": now,
        "ingredient_ids": ids, "raw_ingredients": raw, "unresolved_ingredients": unresolved,
        "ingredient_resolution_complete": not unresolved,
    }
    if body.get("category_id") not in config.categories:
        raise ValueError("Product category is not configured")
    # Display images must be published assets; arbitrary source URLs are not emitted.
    import re
    if not isinstance(body["image_path"], str) or not re.fullmatch(
        r"/products/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)", body["image_path"],
    ):
        body["image_path"] = ""
    for name in ("source_updated_at", "ingested_at"):
        timestamp = datetime.fromisoformat(body[name].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Source timestamps require an explicit timezone")
        body[name] = timestamp.astimezone(UTC).isoformat()
    body["matching_hash"] = matching_hash(body)
    body["record_hash"] = record_hash(body)
    return CanonicalProduct.model_validate(body)
