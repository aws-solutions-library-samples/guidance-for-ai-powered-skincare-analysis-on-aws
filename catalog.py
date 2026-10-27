"""Catalog configuration loader.

Reads data/catalog.yaml and exposes the product schema mapping,
categories, and display preferences to the rest of the application.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REQUIRED_SCHEMA_FIELDS = ("category_field", "name_field", "ingredients_field")


class CatalogValidationError(Exception):
    """Raised when catalog.yaml is missing required configuration."""


@dataclass(frozen=True)
class SchemaMapping:
    """Maps customer CSV/DB column names to system-internal field names."""

    category_field: str = "product_type"
    name_field: str = "product_name"
    ingredients_field: str = "ingredients"
    price_field: str = "price"
    image_field: str = "image_url"


@dataclass(frozen=True)
class CatalogConfig:
    """Complete catalog configuration loaded from catalog.yaml."""

    categories: tuple[str, ...] = ()
    schema: SchemaMapping = field(default_factory=SchemaMapping)
    currency: str = "£"


@lru_cache(maxsize=1)
def load_catalog() -> CatalogConfig:
    """Load and cache catalog configuration from data/catalog.yaml.

    Raises:
        CatalogValidationError: If required fields are missing or empty.
    """
    catalog_path = Path(__file__).resolve().parent / "data" / "catalog.yaml"

    if not catalog_path.is_file():
        raise CatalogValidationError(
            f"Catalog file not found: {catalog_path}\n"
            "Create data/catalog.yaml with your product categories and schema mapping. "
            "See the README catalog example for reference."
        )

    try:
        with catalog_path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise CatalogValidationError(f"{catalog_path} contains invalid YAML") from exc

    if not raw or not isinstance(raw, dict):
        raise CatalogValidationError(
            f"{catalog_path} is empty or malformed. "
            "It must be a YAML file with 'categories' and 'schema' keys."
        )

    schema_raw = raw.get("schema", {})
    if not isinstance(schema_raw, dict) or not schema_raw:
        raise CatalogValidationError(
            f"{catalog_path} is missing the 'schema' section. "
            "Define at least: category_field, name_field, ingredients_field."
        )

    missing = [
        name for name in REQUIRED_SCHEMA_FIELDS
        if not isinstance(schema_raw.get(name), str) or not schema_raw[name].strip()
    ]
    if missing:
        raise CatalogValidationError(
            f"{catalog_path} is missing required schema fields: {missing}\n"
            "These fields map your CSV columns to the system. "
            "See data/catalog.yaml for examples."
        )
    for name in ("price_field", "image_field"):
        if name in schema_raw and (
            not isinstance(schema_raw[name], str) or not schema_raw[name].strip()
        ):
            raise CatalogValidationError(f"schema.{name} must be a nonempty string")

    categories = raw.get("categories", [])
    if (
        not isinstance(categories, list)
        or len(categories) < 2
        or any(not isinstance(category, str) or not category.strip() for category in categories)
        or len(set(categories)) != len(categories)
    ):
        raise CatalogValidationError(
            f"{catalog_path} must define at least two unique, nonempty categories "
            "(e.g. Cleanser, Serum)."
        )
    currency = raw.get("currency", "£")
    if not isinstance(currency, str):
        raise CatalogValidationError("currency must be a string")

    schema = SchemaMapping(
        category_field=schema_raw["category_field"],
        name_field=schema_raw["name_field"],
        ingredients_field=schema_raw["ingredients_field"],
        price_field=schema_raw.get("price_field", "price"),
        image_field=schema_raw.get("image_field", "image_url"),
    )

    return CatalogConfig(
        categories=tuple(categories),
        schema=schema,
        currency=currency,
    )
