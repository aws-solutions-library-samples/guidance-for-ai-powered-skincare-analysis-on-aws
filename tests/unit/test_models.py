import pytest
from pydantic import ValidationError

from agents.bedrock_schema import strict_tool_schema
from agents.models import (
    IngredientDetail, IngredientsAnalysisOutput, ProductExplanation,
    SkinMetrics, StepAnalysisResult,
)


@pytest.mark.parametrize("field", tuple(SkinMetrics.model_fields))
@pytest.mark.parametrize("invalid", [-1, 101, 1000])
def test_skin_metric_bounds(field, invalid):
    metrics = dict.fromkeys(SkinMetrics.model_fields, 50)
    metrics[field] = invalid
    with pytest.raises(ValidationError):
        SkinMetrics(**metrics)


@pytest.mark.parametrize("boundary", [0, 100])
def test_skin_metric_endpoints_are_valid(boundary):
    assert SkinMetrics(**dict.fromkeys(SkinMetrics.model_fields, boundary))


def test_duplicate_steps_are_rejected_before_graph_construction(routine_state):
    plan = routine_state["step_analysis_data"]
    plan["routine_steps"][1]["step_name"] = "Cleanser"
    with pytest.raises(ValidationError):
        StepAnalysisResult.model_validate(plan)


@pytest.mark.parametrize("count", [0, 1, 9])
def test_routine_size_limits(routine_state, count):
    plan = routine_state["step_analysis_data"]
    plan["routine_steps"] = [
        {**plan["routine_steps"][0], "step_name": f"Step {index}"}
        for index in range(count)
    ]
    plan["routine_summary"]["total_steps"] = count
    with pytest.raises(ValidationError):
        StepAnalysisResult.model_validate(plan)


def test_summary_count_must_match_actual_steps(routine_state):
    plan = routine_state["step_analysis_data"]
    plan["routine_summary"]["total_steps"] = 7
    with pytest.raises(ValidationError):
        StepAnalysisResult.model_validate(plan)


@pytest.mark.parametrize("identity", [None, "", " ", "not an id", "a" * 129])
def test_ingredient_identity_is_validated_before_search(identity):
    value = {
        "name": "Glycerin", "benefit": "Hydration", "why_for_you": "Comfort",
        "usage": "Follow the label",
    }
    if identity is not None:
        value["ingredient_id"] = identity
    with pytest.raises(ValidationError):
        IngredientDetail.model_validate(value)


def test_native_schema_requires_the_canonical_ingredient_identity():
    schema = strict_tool_schema(IngredientsAnalysisOutput.model_json_schema())
    detail = schema["$defs"]["IngredientDetail"]
    assert "ingredient_id" in detail["required"]
    identity = detail["properties"]["ingredient_id"]
    assert "default" not in identity
    assert identity["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    assert "minLength=1" in detail["properties"]["benefit"]["description"]


@pytest.mark.parametrize("benefit", ["", " \n"])
def test_ingredient_benefit_cannot_render_as_blank(benefit):
    with pytest.raises(ValidationError):
        IngredientDetail(
            ingredient_id="demo-glycerin", name="Glycerin", benefit=benefit,
            why_for_you="Comfort", usage="Follow the label",
        )


@pytest.mark.parametrize("field", ["why_for_you", "usage_tip"])
@pytest.mark.parametrize("value", ["", " \n"])
def test_product_explanation_cannot_render_as_blank(field, value):
    fields = {
        "product_id": "example-product", "why_for_you": "Helps maintain comfort.",
        "usage_tip": "Use in the morning at the cleansing step.",
    }
    fields[field] = value
    with pytest.raises(ValidationError):
        ProductExplanation.model_validate(fields)
