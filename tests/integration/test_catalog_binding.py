import asyncio
import json

import pytest

from agents.catalog_binding import explanation_input, render_products, safe_product_image
from agents.compile_node import CompileNode
from agents.models import IngredientDetail, ProductExplanations, StepAnalysisResult
from agents.search.contracts import SelectedProduct
from tests.search_fixtures import product


@pytest.fixture
def explanation_case(routine_state):
    plan = StepAnalysisResult.model_validate(routine_state["step_analysis_data"])
    ingredients = routine_state["ingredients_outputs"]["ingredients_Cleanser"].model_copy(deep=True)
    ingredients.key_ingredients.extend([
        IngredientDetail(
            ingredient_id="ing-b", name="Squalane", benefit="Emollience",
            why_for_you="Comfort for dry skin", usage="Ingredient-level context",
        ),
        IngredientDetail(
            ingredient_id="ing-unmatched", name="Unmatched ingredient", benefit="UNMATCHED",
            why_for_you="UNMATCHED reasoning", usage="UNMATCHED directions",
        ),
    ])
    ingredients.analysis_notes = "UNMATCHED combined ingredient rationale"
    result = routine_state["search_results"]["products_Cleanser"].model_copy(update={
        "products": tuple(SelectedProduct(
            product=product(f"product-{index}", ingredient_ids=[identifier]),
            matched_ingredient_ids=(identifier,), matched_must_have_ingredient_ids=(),
            preferred_count=3,
        ) for index, identifier in enumerate(("ing-a", "ing-b"))),
    })
    return result, ingredients, plan


def test_explanation_input_joins_only_each_products_matched_reasoning(explanation_case):
    result, ingredients, plan = explanation_case
    before = [value.model_dump(mode="json") for value in explanation_case]
    context = explanation_input(result, ingredients, plan)
    assert context["user_profile"] == plan.user_profile.model_dump(mode="json")
    assert context["routine_context"]["current_step"] == plan.routine_steps[0].model_dump(mode="json")
    assert context["routine_context"]["ordered_steps"] == [
        {"step_name": step.step_name, "when": step.when} for step in plan.routine_steps
    ]
    assert context["routine_context"]["summary"] == plan.routine_summary.model_dump(mode="json")
    approved = context["approved_products"]["top_recommendations"]
    assert [item["product_id"] for item in approved] == ["product-0", "product-1"]
    for index, item in enumerate(approved):
        assert item["matched_ingredient_reasoning"] == [
            ingredients.key_ingredients[index].model_dump(mode="json")
        ]
        assert "why_for_you" not in item and "usage_tip" not in item
        assert item["price"] == "GBP 10.00"
    assert "UNMATCHED" not in json.dumps(context)
    assert "Follow the product label" not in json.dumps(context)
    assert [value.model_dump(mode="json") for value in explanation_case] == before


@pytest.mark.parametrize("problem", ["wrong_ingredients_step", "absent_plan_step", "duplicate_identity", "unknown_match"])
def test_misbound_explanation_context_is_rejected(explanation_case, problem):
    result, ingredients, plan = explanation_case
    if problem == "wrong_ingredients_step":
        ingredients.step_name = "Serum"
    elif problem == "absent_plan_step":
        plan.routine_steps[0].step_name = "Serum"
    elif problem == "duplicate_identity":
        ingredients.key_ingredients.append(ingredients.key_ingredients[0])
    else:
        result = result.model_copy(update={"products": (
            result.products[0].model_copy(update={"matched_ingredient_ids": ("unknown",)}),
        )})
    with pytest.raises(ValueError):
        explanation_input(result, ingredients, plan)


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
