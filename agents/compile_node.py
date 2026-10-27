"""Finalize canonical records once, then assemble every planned step."""

import asyncio
from typing import Any

from strands.multiagent.base import MultiAgentBase

from .catalog_binding import render_products
from .errors import AnalysisFailure
from .models import CompiledRoutine, CompiledStep, ProductAnalysisOutput, StepAnalysisResult
from .recommendation_nodes import completed


class CompileNode(MultiAgentBase):
    def __init__(self):
        super().__init__()
        self.id = "compile"

    async def invoke_async(self, task: Any, invocation_state=None, **kwargs):
        state = invocation_state or {}
        if state.get("tool_errors"):
            raise ValueError("Catalog tool failures remain unresolved")
        plan = StepAnalysisResult.model_validate(state.get("step_analysis_data"))
        node_ids = [f"products_{step.step_name}" for step in plan.routine_steps]
        ingredients = state.get("ingredients_outputs", {})
        outputs = state.get("products_outputs", {})
        searches = state.get("search_results", {})
        for step, node_id in zip(plan.routine_steps, node_ids, strict=True):
            if (
                node_id not in outputs or node_id not in searches
                or f"ingredients_{step.step_name}" not in ingredients
            ):
                raise ValueError("Missing recommendation output")
            # Refuse malformed/misbound outputs before any final reads.
            output = ProductAnalysisOutput.model_validate(outputs[node_id].model_dump())
            result = searches[node_id]
            if (
                output.step_name != step.step_name
                or result.request.category_id != step.step_name
                or result.request.request_id != state["request_id"]
                or [p.product_id for p in output.top_recommendations]
                != [p.product.product_id for p in result.products]
            ):
                raise ValueError("Recommendation binding changed")
        finalized = await asyncio.to_thread(
            state["product_service"].finalize, tuple(searches[node_id] for node_id in node_ids),
        )
        if len(finalized) != len(node_ids):
            raise ValueError("Finalization omitted a planned step")
        compiled = []
        for step, node_id, result in zip(plan.routine_steps, node_ids, finalized, strict=True):
            previous = searches[node_id]
            if result.request != previous.request:
                raise ValueError("Finalization changed the bound search request")
            ingredient_output = ingredients[f"ingredients_{step.step_name}"]
            if ingredient_output.step_name != step.step_name or not ingredient_output.key_ingredients:
                raise ValueError("Ingredient output is empty or belongs to another step")
            names = {item.ingredient_id: item.name for item in ingredient_output.key_ingredients}
            explanation = state.get("product_explanations", {}).get(node_id)
            if explanation is not None:
                # Keep approved explanations only for surviving IDs in original order.
                survivors = {item.product.product_id for item in result.products}
                explanation = explanation.model_copy(update={
                    "products": [item for item in explanation.products if item.product_id in survivors],
                }) if survivors else None
            output = render_products(
                result, names, explanation,
                explanation_hashes=state.get("explanation_hashes", {}).get(node_id),
                currency_minor_units=state["product_service"].config.currency_minor_units,
            )
            if state.get("api_version", 1) == 1 and output.status == "no_match":
                raise AnalysisFailure("NO_MATCHING_PRODUCTS")
            compiled.append(CompiledStep(
                step_name=step.step_name, when=step.when,
                description=step.justification, why_for_you=step.why_this_step_for_you,
                ingredients=ingredient_output.key_ingredients,
                products=output.top_recommendations,
                recommendation_status=output.status, no_match_reason=output.reason,
            ))
        return completed(self.id, CompiledRoutine(
            user_profile=plan.user_profile, routine_steps=compiled,
            api_version=state.get("api_version", 1), applied_preferences=state["preferences"],
        ))
