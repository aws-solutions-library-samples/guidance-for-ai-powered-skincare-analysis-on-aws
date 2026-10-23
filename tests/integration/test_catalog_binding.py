import asyncio
import json

import pytest

import agentcore_entrypoint
from agents.catalog_binding import bind_products, safe_product_image
from agents.compile_node import CompileNode


def test_fabricated_catalog_id_is_rejected(routine_state):
    output = routine_state["products_outputs"]["products_Cleanser"]
    output.top_recommendations[0].product_id = "invented-product"
    with pytest.raises(ValueError, match="catalog query"):
        bind_products(output, "products_Cleanser", routine_state["trusted_products"])


def test_product_cannot_be_selected_from_another_step(routine_state):
    output = routine_state["products_outputs"]["products_Cleanser"]
    output.top_recommendations[0].product_id = "id-Sunscreen"
    with pytest.raises(ValueError):
        bind_products(output, "products_Cleanser", routine_state["trusted_products"])


def test_duplicate_ids_and_missing_query_are_rejected(routine_state):
    output = routine_state["products_outputs"]["products_Cleanser"]
    with pytest.raises(ValueError):
        bind_products(output, "products_Cleanser", {})
    output.top_recommendations.append(output.top_recommendations[0])
    with pytest.raises(ValueError):
        bind_products(output, "products_Cleanser", routine_state["trusted_products"])


def test_model_cannot_override_price_name_score_ingredients_or_image(routine_state):
    output = routine_state["products_outputs"]["products_Cleanser"]
    selection = output.top_recommendations[0]
    selection.name = "Fabricated product"
    selection.price = "£0.01"
    selection.match_score = "999%"
    selection.matched_ingredients = ["fabricated ingredient"]
    selection.image_url = "https://attacker.invalid/track?secret=data"
    result = bind_products(output, "products_Cleanser", routine_state["trusted_products"])
    product = result.top_recommendations[0]
    assert product.name == "Example Cleanser"
    assert product.price == "£12.00"
    assert product.match_score == "100%"
    assert product.matched_ingredients == ["Glycerin"]
    assert product.image_url == "/products/example.jpg"


def test_compiler_revalidates_catalog_binding(routine_state):
    routine_state["products_outputs"]["products_Cleanser"].top_recommendations[0].price = "£0.01"
    result = asyncio.run(CompileNode().invoke_async("compile", invocation_state=routine_state))
    serialized = json.dumps(result.to_dict())
    assert "0.01" not in serialized
    assert "12.00" in serialized
    routine_state["trusted_products"].clear()
    with pytest.raises(ValueError):
        asyncio.run(CompileNode().invoke_async("compile", invocation_state=routine_state))


@pytest.mark.parametrize("value", [
    "https://attacker.invalid/x.jpg", "//attacker.invalid/x.jpg", "data:image/png;base64,AAA",
    "javascript:alert(1)", "/products/../secret.jpg", "/products/%2f%2fattacker.invalid/x.jpg",
    "/products/a.jpg?track=anything", "/products/a.svg", None,
])
def test_unapproved_images_are_discarded(value):
    assert safe_product_image(value) == ""


def test_approved_catalog_asset_is_preserved():
    assert safe_product_image("/products/cleanser/front_1.webp") == "/products/cleanser/front_1.webp"
