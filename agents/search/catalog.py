"""Versioned ingredient discovery and control records, read by bounded keys."""

import hashlib
import math
from typing import Literal

from pydantic import Field

from .budget import SearchBudget
from .contracts import Contract, Identifier, IndexReadiness, SearchConfiguration
from .errors import InvalidSearchResponse, SearchUnavailable
from .repository import native_numbers


def normalize_name(name: str) -> str:
    if not isinstance(name, str) or not 1 <= len(name) <= 256 or not name.strip():
        raise ValueError("Ingredient names must contain 1–256 characters")
    return " ".join(name.lower().split())


def alias_key(version: str, name: str) -> str:
    digest = hashlib.sha256(normalize_name(name).encode("utf-8")).hexdigest()
    return f"ALIAS#{version}#{digest}"


def ingredient_key(version: str, ingredient_id: str) -> str:
    return f"INGREDIENT#{version}#{ingredient_id}"


def summary_key(version: str, category: str) -> str:
    digest = hashlib.sha256(category.encode("utf-8")).hexdigest()
    return f"SUMMARY#{version}#{digest}"


class IngredientEntry(Contract):
    ingredient_id: Identifier
    display_name: str = Field(min_length=1, max_length=256)
    taxonomy_version: Identifier
    aliases: tuple[str, ...] = Field(default=(), max_length=50)
    review_state: Literal["reviewed", "synthetic_fixture"]
    provenance: str = Field(min_length=1, max_length=1024)


class CatalogMetadata:
    def __init__(self, resource, *, table_name: str, catalog_id: str) -> None:
        if not table_name or not catalog_id:
            raise ValueError("Catalog metadata table and scope are required")
        self.resource = resource
        self.table_name = table_name
        self.catalog_id = catalog_id

    def values(self, keys: tuple[str, ...], budget: SearchBudget | None = None) -> dict:
        if len(keys) > 100 or len(set(keys)) != len(keys):
            raise ValueError("Metadata lookup requires at most 100 distinct keys")
        if not keys:
            return {}
        budget = budget or SearchBudget()
        pending = set(keys)
        result = {}
        while pending:
            budget.require(0.150)
            try:
                response = self.resource.batch_get_item(RequestItems={
                    self.table_name: {
                        "Keys": [{"pk": key} for key in sorted(pending)],
                        "ConsistentRead": True,
                    },
                })
            except Exception as exc:
                raise SearchUnavailable("Catalog metadata read failed") from exc
            budget.remaining()
            try:
                responses = response["Responses"]
                tables = response.get("UnprocessedKeys", {})
                if (
                    not isinstance(responses, dict) or set(responses) - {self.table_name}
                    or not isinstance(tables, dict) or set(tables) - {self.table_name}
                ):
                    raise ValueError("Unexpected metadata table")
                rows = responses.get(self.table_name, [])
                outstanding = tables.get(self.table_name, {}).get("Keys", [])
                if not isinstance(rows, list) or not isinstance(outstanding, list):
                    raise ValueError("Invalid metadata result lists")
                if self.table_name in tables and not outstanding:
                    raise ValueError("Pending metadata table omitted keys")
                if tables.get(self.table_name, {}).get("ConsistentRead", True) is not True:
                    raise ValueError("Metadata retry changed consistency")
                unprocessed = set()
                for key in outstanding:
                    if not isinstance(key, dict) or set(key) != {"pk"}:
                        raise ValueError("Invalid metadata pending key")
                    pk = key["pk"]
                    if not isinstance(pk, str) or pk not in pending or pk in unprocessed:
                        raise ValueError("Duplicate or unrequested pending key")
                    unprocessed.add(pk)
                for row in rows:
                    if (
                        not isinstance(row, dict) or row.get("pk") not in pending
                        or row["pk"] in result or row["pk"] in unprocessed
                        or row.get("catalog_id") != self.catalog_id or "value" not in row
                    ):
                        raise ValueError("Invalid metadata identity or scope")
                    result[row["pk"]] = native_numbers(row["value"])
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise InvalidSearchResponse("Invalid catalog metadata response") from exc
            pending = unprocessed
            if pending:
                budget.retry()
        return result

    def configuration(self) -> SearchConfiguration:
        values = self.values(("CONFIG",))
        try:
            config = SearchConfiguration.model_validate(values["CONFIG"])
            if config.catalog_id != self.catalog_id:
                raise ValueError("Configuration has another catalog")
            return config
        except (KeyError, TypeError, ValueError) as exc:
            raise SearchUnavailable("Catalog configuration is not ready") from exc

    def readiness(self, config: SearchConfiguration, budget: SearchBudget) -> IndexReadiness:
        key = f"READINESS#{config.index_generation}"
        values = self.values((key,), budget)
        try:
            return IndexReadiness.model_validate(values[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise SearchUnavailable("Catalog readiness is unavailable") from exc

    def ingredients(
        self, ids: tuple[str, ...], version: str, *, budget: SearchBudget | None = None,
    ) -> dict[str, IngredientEntry]:
        if len(ids) > 20 or len(ids) != len(set(ids)):
            raise ValueError("At most 20 unique ingredient IDs per lookup")
        keys = {ingredient_key(version, identifier): identifier for identifier in ids}
        values = self.values(tuple(keys), budget)
        result = {}
        try:
            for key, value in values.items():
                ingredient = IngredientEntry.model_validate(value)
                if ingredient.ingredient_id != keys[key] or ingredient.taxonomy_version != version:
                    raise ValueError("Ingredient registry identity/version differs")
                result[ingredient.ingredient_id] = ingredient
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidSearchResponse("Invalid ingredient registry entry") from exc
        return result

    def resolve_names(self, names: tuple[str, ...], version: str) -> list[dict]:
        if not names or len(names) > 20:
            raise ValueError("Resolve between 1 and 20 exact ingredient names")
        keys = [alias_key(version, name) for name in names]
        budget = SearchBudget()
        values = self.values(tuple(dict.fromkeys(keys)), budget)
        resolved = []
        ids = set()
        for key, name in zip(keys, names, strict=True):
            value = values.get(key)
            if value is None:
                resolved.append({"input": name, "status": "unresolved"})
                continue
            if (
                not isinstance(value, dict) or value.get("normalized_name") != normalize_name(name)
                or value.get("taxonomy_version") != version
                or not isinstance(value.get("ingredient_ids"), list)
                or not 1 <= len(value["ingredient_ids"]) <= 20
                or any(not isinstance(identifier, str) for identifier in value["ingredient_ids"])
                or len(set(value["ingredient_ids"])) != len(value["ingredient_ids"])
            ):
                raise InvalidSearchResponse("Invalid exact ingredient alias")
            matches = value["ingredient_ids"]
            if len(matches) > 1:
                resolved.append({"input": name, "status": "ambiguous"})
            else:
                ids.add(matches[0])
                resolved.append({"input": name, "status": "resolved", "ingredient_id": matches[0]})
        entries = self.ingredients(tuple(sorted(ids)), version, budget=budget)
        for item in resolved:
            if item["status"] == "resolved":
                entry = entries.get(item["ingredient_id"])
                if entry is None:
                    raise InvalidSearchResponse("Alias points to an absent registry entry")
                item["display_name"] = entry.display_name
        return resolved

    def summary(self, category: str, config: SearchConfiguration) -> dict:
        if category not in config.categories:
            raise ValueError("Unknown discovery category")
        key = summary_key(config.taxonomy_version, category)
        value = self.values((key,)).get(key)
        if value is None:
            return {"category_id": category, "ingredients": [], "advisory": True, "as_of": None}
        if (
            not isinstance(value, dict) or value.get("category_id") != category
            or value.get("taxonomy_version") != config.taxonomy_version
            or not isinstance(value.get("ingredients"), list) or len(value["ingredients"]) > 30
            or type(value.get("as_of")) not in (int, float)
            or not math.isfinite(value["as_of"]) or value["as_of"] < 0
        ):
            raise InvalidSearchResponse("Invalid ingredient discovery summary")
        ids = []
        for item in value["ingredients"]:
            if (
                not isinstance(item, dict) or not isinstance(item.get("ingredient_id"), str)
                or not isinstance(item.get("display_name"), str)
                or type(item.get("count")) is not int or item["count"] < 0
            ):
                raise InvalidSearchResponse("Invalid discovery ingredient")
            ids.append(item["ingredient_id"])
        if len(ids) != len(set(ids)):
            raise InvalidSearchResponse("Duplicate ingredient discovery entries")
        return {**value, "advisory": True}
