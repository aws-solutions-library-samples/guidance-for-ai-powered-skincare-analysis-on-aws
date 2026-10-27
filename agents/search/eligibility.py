"""Exact ingredient eligibility; one representation for engine and canonical reads."""

from dataclasses import dataclass
from typing import Literal

from .contracts import CanonicalProduct, SearchRequest


@dataclass(frozen=True)
class Predicate:
    field: str
    operation: Literal["eq", "contains", "excludes", "lte"]
    value: str | int | bool

    def matches(self, product: CanonicalProduct) -> bool:
        actual = getattr(product, self.field)
        if self.operation == "eq":
            return actual is not None and actual == self.value
        if self.operation == "contains":
            return actual is not None and self.value in actual
        if self.operation == "excludes":
            return actual is not None and self.value not in actual
        return actual is not None and actual <= self.value

    def query(self) -> dict:
        if self.operation == "lte":
            return {"range": {self.field: {"gte": 0, "lte": self.value}}}
        return {"term": {self.field: self.value}}


def predicates(request: SearchRequest) -> tuple[Predicate, ...]:
    result = [
        Predicate("catalog_id", "eq", request.catalog_id),
        Predicate("category_id", "eq", request.category_id),
        Predicate("schema_version", "eq", request.schema_version),
        Predicate("taxonomy_version", "eq", request.taxonomy_version),
        Predicate("active", "eq", True),
        Predicate("is_deleted", "eq", False),
    ]
    result.extend(Predicate("ingredient_ids", "contains", item) for item in request.must_have_ingredient_ids)
    result.extend(Predicate("ingredient_ids", "excludes", item) for item in request.excluded_ingredient_ids)
    if request.excluded_ingredient_ids:
        result.extend((
            Predicate("ingredient_list_complete", "eq", True),
            Predicate("ingredient_resolution_complete", "eq", True),
        ))
    if request.market:
        result.append(Predicate("market_ids", "contains", request.market))
    if request.currency:
        result.append(Predicate("currency", "eq", request.currency))
    if request.eligibility_mode == "purchasable":
        result.append(Predicate("availability", "eq", "available"))
    if request.max_price_minor is not None:
        result.append(Predicate("price_minor", "lte", request.max_price_minor))
    return tuple(result)


def eligible(product: CanonicalProduct, request: SearchRequest) -> bool:
    return all(predicate.matches(product) for predicate in predicates(request))


def filter_query(request: SearchRequest) -> dict:
    clauses: dict[str, list] = {"filter": [], "must_not": []}
    for predicate in predicates(request):
        clauses["must_not" if predicate.operation == "excludes" else "filter"].append(predicate.query())
    return {"bool": clauses}


def matched_ids(product: CanonicalProduct, request: SearchRequest) -> tuple[str, ...]:
    return tuple(sorted(set(product.ingredient_ids) & set(request.preferred_ingredient_ids)))
