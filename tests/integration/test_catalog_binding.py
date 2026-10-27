import asyncio
import json

import pytest

from agents.catalog_binding import render_products, safe_product_image
from agents.compile_node import CompileNode
from agents.models import ProductExplanations
from tests.search_fixtures import product


@pytest.mark.parametrize("ids", [
    ["invented-product"], ["id-Sunscreen"], ["id-Cleanser", "id-Cleanser"], [],
])
def test_explanation_cannot_replace_add_duplicate_or_omit_ids(routine_state, ids):
    result = routine_state["search_results"]["products_Cleanser"]
    with pytest.raises(ValueError):
        explanation = ProductExplanations(step_name="Cleanser", products=[
            {"product_id": identifier, "why_for_you": "text", "usage_tip": "text"}
            for identifier in ids
        ])
        render_products(result, {"ing-a": "Glycerin"}, explanation)


def test_compiler_discards_fabricated_display_fields(routine_state):
    selection = routine_state["products_outputs"]["products_Cleanser"].top_recommendations[0]
    selection.name, selection.price, selection.match_score = "fabricated", "GBP 0.01", "999%"
    selection.image_url = "https://attacker.invalid/collect"
    result = asyncio.run(CompileNode().invoke_async("compile", invocation_state=routine_state))
    wire = json.dumps(result.to_dict())
    assert all(value not in wire for value in ("fabricated", "0.01", "999%", "attacker.invalid"))
    assert "GBP 12.00" in wire


def test_display_update_invalidates_generated_explanation(routine_state):
    result = routine_state["search_results"]["products_Cleanser"]
    old = result.products[0].product
    explanation = ProductExplanations(step_name="Cleanser", products=[{
        "product_id": old.product_id, "why_for_you": "Old formulation claim", "usage_tip": "Old directions",
    }])
    revised = product(
        **{**old.model_dump(), "source_revision": 2, "name": "Updated product"},
    )
    result = result.model_copy(update={"products": (
        result.products[0].model_copy(update={"product": revised}),
    )})
    output = render_products(result, {"ing-a": "Glycerin"}, explanation,
                             explanation_hashes={old.product_id: old.record_hash})
    assert output.top_recommendations[0].name == "Updated product"
    assert output.top_recommendations[0].why_for_you != "Old formulation claim"


@pytest.mark.parametrize("value", [
    "https://attacker.invalid/x.jpg", "//attacker.invalid/x.jpg", "data:image/png;base64,AAA",
    "javascript:alert(1)", "/products/../secret.jpg", "/products/%2f%2fattacker.invalid/x.jpg",
    "/products/a.jpg?track=anything", "/products/a.svg", None,
])
def test_unapproved_images_are_discarded(value):
    assert safe_product_image(value) == ""


def test_approved_catalog_asset_is_preserved():
    assert safe_product_image("/products/cleanser/front_1.webp") == "/products/cleanser/front_1.webp"
