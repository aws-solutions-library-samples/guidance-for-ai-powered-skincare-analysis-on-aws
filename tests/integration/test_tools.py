"""Tool failures must survive LLM recovery until a successful repository retry."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agents.tools import find_products_for_step, get_available_ingredients_for_step
from catalog import SchemaMapping


@pytest.fixture
def context():
    service = Mock()
    service.schema = SchemaMapping()
    return SimpleNamespace(invocation_state={"product_service": service}, agent=SimpleNamespace(name="products_Cleanser"))


def test_ingredient_lookup_failure_then_retry_clears_only_its_error(context):
    service = context.invocation_state["product_service"]
    service.get_available_ingredients.side_effect = [
        RuntimeError("database unavailable"),
        [{"ingredient": "Glycerin", "count": 2, "product_count": 3}],
    ]
    context.invocation_state["tool_errors"] = {"products_Sunscreen": "still unavailable"}
    failed = json.loads(get_available_ingredients_for_step("Cleanser", context))
    assert failed["error"] == "database unavailable"
    assert "ingredients_Cleanser" in context.invocation_state["tool_errors"]
    success = json.loads(get_available_ingredients_for_step("Cleanser", context))
    assert success["total_products"] == 3
    assert context.invocation_state["tool_errors"] == {"products_Sunscreen": "still unavailable"}


def test_empty_products_are_an_explicit_failure(context):
    context.invocation_state["product_service"].find_best_products.return_value = []
    result = json.loads(find_products_for_step("Cleanser", ["Glycerin"], context))
    assert result["error"]
    assert context.invocation_state["tool_errors"]["products_Cleanser"]


def test_product_retry_recovers_with_actual_catalog_values(context):
    service = context.invocation_state["product_service"]
    service.find_best_products.side_effect = [
        RuntimeError("query unavailable"),
        [{
            "product_id": "cleanser-1", "product_name": "Gentle Cleanser", "price": "£7.00", "image_url": "/products/image.jpg",
            "ingredients": ["Glycerin"], "matched_ingredients": ["Glycerin"], "match_score": "100%",
        }],
    ]
    assert "error" in json.loads(find_products_for_step("Cleanser", ["Glycerin"], context))
    success = json.loads(find_products_for_step("Cleanser", ["Glycerin"], context))
    assert success["products"][0]["product_name"] == "Gentle Cleanser"
    assert success["products"][0]["image_url"] == "/products/image.jpg"
    assert context.invocation_state["tool_errors"] == {}
    assert context.invocation_state["trusted_products"]["products_Cleanser"]["cleanser-1"]["price"] == "£7.00"


def test_tool_cannot_query_a_different_nodes_category(context):
    result = json.loads(find_products_for_step("Sunscreen", ["Glycerin"], context))
    assert result["error"]
    context.invocation_state["product_service"].find_best_products.assert_not_called()
    assert context.invocation_state["trusted_products"] == {}


@pytest.mark.parametrize("ingredients", [[], [" "], [1], '["Glycerin"]'])
def test_invalid_ingredient_inputs_do_not_query_database(context, ingredients):
    result = json.loads(find_products_for_step("Cleanser", ingredients, context))
    assert "error" in result
    context.invocation_state["product_service"].find_best_products.assert_not_called()
