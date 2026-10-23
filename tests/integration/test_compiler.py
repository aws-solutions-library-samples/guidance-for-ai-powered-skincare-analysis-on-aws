"""Use the real deterministic compiler and validated agent output models."""

import asyncio
import json

import pytest
from strands.multiagent.base import Status

from agents.compile_node import CompileNode


def compile_routine(state):
    return asyncio.run(CompileNode().invoke_async("compile", invocation_state=state))


def test_complete_routine_preserves_plan_order_and_recommendations(routine_state):
    result = compile_routine(routine_state)
    assert result.status == Status.COMPLETED
    content = result.results["compile"].result.message["content"]
    routine = json.loads(content[0]["text"])
    assert [step["step_name"] for step in routine["routine_steps"]] == [
        "Cleanser", "Sunscreen",
    ]
    assert routine["user_profile"]["skin_type"] == "Dry"
    for step in routine["routine_steps"]:
        assert step["ingredients"][0]["name"] == "Glycerin"
        assert step["products"][0]["image_url"] == "/products/example.jpg"


@pytest.mark.parametrize("output_key,node_id", [
    ("ingredients_outputs", "ingredients_Cleanser"),
    ("products_outputs", "products_Sunscreen"),
])
def test_missing_output_fails_instead_of_silently_completing(routine_state, output_key, node_id):
    del routine_state[output_key][node_id]
    with pytest.raises(ValueError, match="(?i)(missing|incomplete)"):
        compile_routine(routine_state)


@pytest.mark.parametrize("output_key,node_id,field", [
    ("ingredients_outputs", "ingredients_Cleanser", "key_ingredients"),
    ("products_outputs", "products_Sunscreen", "top_recommendations"),
])
def test_empty_output_is_not_a_completed_recommendation(routine_state, output_key, node_id, field):
    setattr(routine_state[output_key][node_id], field, [])
    with pytest.raises(ValueError):
        compile_routine(routine_state)


def test_mismatched_step_output_cannot_be_attached_to_another_step(routine_state):
    routine_state["ingredients_outputs"]["ingredients_Cleanser"].step_name = "Serum"
    with pytest.raises(ValueError):
        compile_routine(routine_state)


def test_missing_plan_is_not_replaced_with_unknown_profile():
    with pytest.raises(ValueError):
        compile_routine({})


def test_unresolved_tool_error_prevents_success_even_with_outputs(routine_state):
    routine_state["tool_errors"] = {"products_Cleanser": "catalog lookup failed"}
    with pytest.raises(ValueError, match="(?i)(tool|catalog)"):
        compile_routine(routine_state)
