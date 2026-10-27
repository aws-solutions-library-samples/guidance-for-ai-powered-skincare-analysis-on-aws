"""Validated exact-ID contracts shared by publication, search and the API."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
]
Category = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
Currency = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
Market = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{2}$")]
MinorUnits = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
Revision = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
IngredientIds = Annotated[tuple[Identifier, ...], Field(max_length=20)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MustHaveCategory(Contract):
    category_id: Category
    ingredient_ids: IngredientIds = Field(min_length=1)

    @model_validator(mode="after")
    def deduplicate(self) -> Self:
        object.__setattr__(self, "ingredient_ids", tuple(sorted(set(self.ingredient_ids))))
        return self


class Preferences(Contract):
    """User constraints; ingredient-agent choices are a separate input."""

    excluded_ingredient_ids: IngredientIds = ()
    must_have_by_category: tuple[MustHaveCategory, ...] = Field(default=(), max_length=8)
    market: Market | None = None
    currency: Currency | None = None
    max_price_minor: MinorUnits | None = None

    @model_validator(mode="after")
    def validate_constraints(self) -> Self:
        categories = [entry.category_id for entry in self.must_have_by_category]
        if len(categories) != len(set(categories)):
            raise ValueError("Must-have categories must be unique")
        if sum(len(entry.ingredient_ids) for entry in self.must_have_by_category) > 20:
            raise ValueError("At most 20 must-have ingredient references are allowed")
        excluded = set(self.excluded_ingredient_ids)
        if any(excluded.intersection(entry.ingredient_ids) for entry in self.must_have_by_category):
            raise ValueError("An ingredient cannot be both mandatory and excluded")
        object.__setattr__(self, "excluded_ingredient_ids", tuple(sorted(excluded)))
        return self

    def required_for(self, category: str) -> tuple[str, ...]:
        return next(
            (entry.ingredient_ids for entry in self.must_have_by_category
             if entry.category_id == category),
            (),
        )


class SearchConfiguration(Contract):
    catalog_id: Identifier
    configuration_id: Identifier
    index_generation: Annotated[
        str, StringConstraints(strict=True, pattern=r"^products-[a-z0-9][a-z0-9_-]{0,118}$")
    ]
    taxonomy_version: Identifier
    schema_version: Literal["2.0"] = "2.0"
    eligibility_mode: Literal["catalog", "purchasable"] = "catalog"
    default_market: Market | None = None
    default_currency: Currency | None = None
    supported_markets: tuple[Market, ...] = Field(default=(), max_length=50)
    supported_currencies: tuple[Currency, ...] = Field(default=(), max_length=50)
    currency_minor_units: dict[Currency, Annotated[int, Field(strict=True, ge=0, le=4)]] = Field(
        default_factory=lambda: {"GBP": 2, "EUR": 2, "USD": 2}, max_length=50,
    )
    categories: tuple[Category, ...] = Field(min_length=2, max_length=100)
    candidate_limit: int = Field(default=100, strict=True, ge=3, le=100)
    initial_hydration: int = Field(default=10, strict=True, ge=3, le=10)
    step_deadline_seconds: float = Field(default=1.2, gt=0, le=1.2, allow_inf_nan=False)
    search_timeout_seconds: float = Field(default=0.350, gt=0, le=0.350, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_defaults(self) -> Self:
        if self.default_market and self.default_market not in self.supported_markets:
            raise ValueError("Default market is unsupported")
        if self.default_currency and self.default_currency not in self.supported_currencies:
            raise ValueError("Default currency is unsupported")
        if self.eligibility_mode == "purchasable" and (
            not self.default_market or not self.default_currency
        ):
            raise ValueError("Purchasable mode needs a market and currency")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("Categories must be unique")
        if len(set(self.supported_markets)) != len(self.supported_markets) or len(set(self.supported_currencies)) != len(self.supported_currencies):
            raise ValueError("Market and currency options must be unique")
        if set(self.supported_currencies) - set(self.currency_minor_units):
            raise ValueError("Every supported currency needs an explicit minor-unit exponent")
        if self.initial_hydration > self.candidate_limit:
            raise ValueError("Initial hydration exceeds candidate limit")
        return self

    def validate_preferences(self, preferences: Preferences) -> None:
        if preferences.market and preferences.market not in self.supported_markets:
            raise ValueError("Unsupported market")
        if preferences.currency and preferences.currency not in self.supported_currencies:
            raise ValueError("Unsupported currency")
        if preferences.max_price_minor is not None and not (
            preferences.currency or self.default_currency
        ):
            raise ValueError("A price limit requires a currency")
        if any(entry.category_id not in self.categories for entry in preferences.must_have_by_category):
            raise ValueError("Unknown must-have category")


class SearchRequest(Contract):
    request_id: Identifier
    step_id: Identifier
    catalog_id: Identifier
    category_id: Category
    configuration_id: Identifier
    index_generation: str
    taxonomy_version: Identifier
    schema_version: Literal["2.0"] = "2.0"
    eligibility_mode: Literal["catalog", "purchasable"] = "catalog"
    preferred_ingredient_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=5)
    must_have_ingredient_ids: IngredientIds = ()
    excluded_ingredient_ids: IngredientIds = ()
    market: Market | None = None
    currency: Currency | None = None
    max_price_minor: MinorUnits | None = None

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if set(self.must_have_ingredient_ids) & set(self.excluded_ingredient_ids):
            raise ValueError("Must-haves conflict with exclusions")
        for name in ("preferred_ingredient_ids", "must_have_ingredient_ids", "excluded_ingredient_ids"):
            ids = set(getattr(self, name))
            if name == "preferred_ingredient_ids":
                ids -= set(self.excluded_ingredient_ids)
            object.__setattr__(self, name, tuple(sorted(ids)))
        if not self.preferred_ingredient_ids:
            raise ValueError("No preferred ingredients remain after exclusions")
        if self.max_price_minor is not None and self.currency is None:
            raise ValueError("Price constraint has no currency")
        if self.eligibility_mode == "purchasable" and (not self.market or not self.currency):
            raise ValueError("Purchasable search needs market and currency")
        return self

    def validate_configuration(self, config: SearchConfiguration) -> None:
        for field in (
            "catalog_id", "configuration_id", "index_generation",
            "taxonomy_version", "schema_version", "eligibility_mode",
        ):
            if getattr(self, field) != getattr(config, field):
                raise ValueError(f"Search request has mismatched {field}")
        if self.category_id not in config.categories:
            raise ValueError("Search category is unsupported")
        if self.market and self.market not in config.supported_markets:
            raise ValueError("Search market is unsupported")
        if self.currency and self.currency not in config.supported_currencies:
            raise ValueError("Search currency is unsupported")


class CanonicalProduct(Contract):
    product_id: Identifier
    catalog_id: Identifier
    category_id: Category
    source_revision: Revision
    taxonomy_version: Identifier
    schema_version: Literal["2.0"] = "2.0"
    name: str = Field(min_length=1, max_length=512)
    brand: str = Field(default="", max_length=512)
    image_path: str = Field(default="", max_length=1024)
    ingredient_ids: tuple[Identifier, ...] = Field(max_length=512)
    raw_ingredients: tuple[Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)], ...] = Field(max_length=512)
    unresolved_ingredients: tuple[Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)], ...] = Field(default=(), max_length=512)
    ingredient_list_complete: bool = Field(strict=True)
    ingredient_resolution_complete: bool = Field(strict=True)
    price_minor: MinorUnits | None = None
    currency: Currency | None = None
    market_ids: tuple[Market, ...] = Field(default=(), max_length=50)
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    active: bool = Field(strict=True)
    is_deleted: bool = Field(strict=True)
    source_updated_at: str = Field(min_length=1, max_length=40)
    ingested_at: str = Field(min_length=1, max_length=40)
    source_provenance: str = Field(min_length=1, max_length=1024)
    matching_hash: Hash
    record_hash: Hash

    @model_validator(mode="after")
    def validate_contents(self) -> Self:
        object.__setattr__(self, "ingredient_ids", tuple(sorted(set(self.ingredient_ids))))
        object.__setattr__(self, "market_ids", tuple(sorted(set(self.market_ids))))
        if self.ingredient_resolution_complete and self.unresolved_ingredients:
            raise ValueError("Unresolved ingredients contradict complete resolution")
        if self.matching_hash != matching_hash(self.model_dump()):
            raise ValueError("Canonical matching hash is invalid")
        if self.record_hash != record_hash(self.model_dump()):
            raise ValueError("Canonical record hash is invalid")
        # Leave space for DynamoDB attribute names and the immutable outbox
        # envelope beneath the service's 400 KiB item limit.
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=True).encode("utf-8")) > 350_000:
            raise ValueError("Canonical product exceeds the publication size budget")
        return self


MATCHING_FIELDS = (
    "product_id", "catalog_id", "category_id", "schema_version", "taxonomy_version",
    "ingredient_ids", "ingredient_list_complete", "ingredient_resolution_complete",
    "price_minor", "currency", "market_ids", "availability", "active", "is_deleted",
)


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                   allow_nan=False).encode("utf-8")
    ).hexdigest()


def matching_hash(record: dict) -> str:
    values = {field: record.get(field) for field in MATCHING_FIELDS}
    for field in ("ingredient_ids", "market_ids"):
        values[field] = sorted(set(values[field] or ()))
    return _digest(values)


def record_hash(record: dict) -> str:
    # Import/replay timestamps are delivery metadata, not supplier content.
    values = {
        key: value for key, value in record.items()
        if key not in {"record_hash", "matching_hash", "ingested_at"}
    }
    for field in ("ingredient_ids", "market_ids"):
        values[field] = sorted(set(values.get(field) or ()))
    return _digest(values)


class Candidate(Contract):
    product_id: Identifier
    catalog_id: Identifier
    source_revision: Revision
    matching_hash: Hash
    score: float = Field(gt=0, le=5, allow_inf_nan=False)

    @model_validator(mode="after")
    def integer_score(self) -> Self:
        if not self.score.is_integer():
            raise ValueError("Exact-match score must be an integer")
        return self


class SelectedProduct(Contract):
    product: CanonicalProduct
    matched_ingredient_ids: tuple[Identifier, ...]
    matched_must_have_ingredient_ids: tuple[Identifier, ...]
    preferred_count: int = Field(strict=True, ge=1, le=5)

    @property
    def matched_count(self) -> int:
        return len(self.matched_ingredient_ids)


class SearchTrace(Contract):
    retrieved: int = Field(ge=0, le=100)
    hydrated: int = Field(ge=0, le=100)
    hydration_batches: int = Field(ge=0, le=2)
    dependency_retries: int = Field(ge=0, le=1)
    dropped_missing: int = Field(ge=0)
    dropped_ineligible: int = Field(ge=0)
    dropped_changed: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)


class SearchResult(Contract):
    request: SearchRequest
    status: Literal["matched", "no_match"]
    reason: Literal["no_matching_products", "catalog_changed"] | None = None
    products: tuple[SelectedProduct, ...] = Field(max_length=3)
    trace: SearchTrace

    @model_validator(mode="after")
    def valid_outcome(self) -> Self:
        if self.status == "matched" and (not self.products or self.reason is not None):
            raise ValueError("Matched results require products and no no-match reason")
        if self.status == "no_match" and (self.products or self.reason is None):
            raise ValueError("No-match requires a reason and no products")
        ids = [item.product.product_id for item in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate selected products")
        return self


class IndexReadiness(Contract):
    catalog_id: Identifier
    configuration_id: Identifier
    index_generation: str
    healthy: bool = Field(strict=True)
    checked_at: float = Field(ge=0, allow_inf_nan=False)
    oldest_pending_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_healthy: bool = Field(strict=True)
