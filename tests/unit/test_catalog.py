import pytest
import yaml

import catalog


@pytest.fixture
def catalog_file(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    directory.mkdir()
    monkeypatch.setattr(catalog, "__file__", str(tmp_path / "catalog.py"))
    catalog.load_catalog.cache_clear()
    yield directory / "catalog.yaml"
    catalog.load_catalog.cache_clear()


@pytest.fixture
def valid_catalog():
    return {
        "categories": ["Cleanser", "Sunscreen"],
        "schema": {
            "category_field": "category", "name_field": "name",
            "ingredients_field": "inci",
        },
    }


def test_valid_customer_schema_and_defaults(catalog_file, valid_catalog):
    catalog_file.write_text(yaml.safe_dump(valid_catalog))
    result = catalog.load_catalog()
    assert result.categories == ("Cleanser", "Sunscreen")
    assert result.schema.ingredients_field == "inci"
    assert result.schema.price_field == "price"
    assert result.currency == "£"


@pytest.mark.parametrize("content", ["", "[]", "categories: [", "null"])
def test_malformed_or_empty_catalog_has_actionable_error(catalog_file, content):
    catalog_file.write_text(content)
    with pytest.raises(catalog.CatalogValidationError):
        catalog.load_catalog()


def test_missing_catalog_has_actionable_error(catalog_file):
    with pytest.raises(catalog.CatalogValidationError, match="Catalog file not found"):
        catalog.load_catalog()


@pytest.mark.parametrize("categories", [
    [], ["Cleanser"], ["Cleanser", "Cleanser"], ["Cleanser", ""],
    ["Cleanser", 1], "Cleanser, Sunscreen",
])
def test_invalid_categories_fail_before_agent_planning(catalog_file, valid_catalog, categories):
    valid_catalog["categories"] = categories
    catalog_file.write_text(yaml.safe_dump(valid_catalog))
    with pytest.raises(catalog.CatalogValidationError):
        catalog.load_catalog()


@pytest.mark.parametrize("schema", [
    {}, [], "schema", {"category_field": "category"},
    {"category_field": 1, "name_field": "name", "ingredients_field": "inci"},
    {"category_field": " ", "name_field": "name", "ingredients_field": "inci"},
])
def test_invalid_schema_mapping_is_rejected(catalog_file, valid_catalog, schema):
    valid_catalog["schema"] = schema
    catalog_file.write_text(yaml.safe_dump(valid_catalog))
    with pytest.raises(catalog.CatalogValidationError):
        catalog.load_catalog()
