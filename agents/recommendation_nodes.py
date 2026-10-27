"""Validated ingredient choice → deterministic selection → explanation."""

import asyncio
import json
import logging
import time
from typing import Any

from strands.agent.agent_result import AgentResult
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status

from .catalog_binding import render_products
from .errors import AnalysisFailure
from .models import IngredientsAnalysisOutput, ProductExplanations

logger = logging.getLogger(__name__)
EXPLANATION_DEADLINE_SECONDS = 10


def completed(node_id, output) -> MultiAgentResult:
    result = AgentResult(
        stop_reason="end_turn",
        message={"role": "assistant", "content": [{"text": output.model_dump_json()}]},
        metrics=None, state={}, structured_output=output,
    )
    return MultiAgentResult(
        status=Status.COMPLETED,
        results={node_id: NodeResult(result=result, status=Status.COMPLETED)},
    )


class IngredientSelectionNode(MultiAgentBase):
    def __init__(self, category, agent):
        super().__init__()
        self.category, self.agent = category, agent
        self.id = f"ingredients_{category}"

    async def invoke_async(self, task: Any, invocation_state=None, **kwargs):
        state = invocation_state
        result = await self.agent.invoke_async(task, invocation_state=state)
        if result.stop_reason == "guardrail_intervened":
            raise AnalysisFailure("GUARDRAIL_BLOCKED")
        if self.id in state.get("tool_errors", {}):
            raise AnalysisFailure("SERVICE_UNAVAILABLE")
        output = IngredientsAnalysisOutput.model_validate(result.structured_output)
        output = await asyncio.to_thread(
            state["product_service"].validate_ingredients, output, self.category, state["preferences"],
        )
        # Store before returning; downstream scheduling does not depend on SSE consumption.
        state["ingredients_outputs"][self.id] = output
        return completed(self.id, output)


class ProductSelectionNode(MultiAgentBase):
    def __init__(self, category, agent):
        super().__init__()
        self.category, self.agent = category, agent
        self.id = f"products_{category}"

    async def invoke_async(self, task: Any, invocation_state=None, **kwargs):
        state = invocation_state
        ingredients = state["ingredients_outputs"][f"ingredients_{self.category}"]
        scheduled_at = time.monotonic()
        result = await asyncio.to_thread(
            state["product_service"].search, ingredients, state["preferences"],
            state["request_id"], scheduled_at=scheduled_at,
        )
        state["search_results"][self.id] = result
        names = {item.ingredient_id: item.name for item in ingredients.key_ingredients}
        hashes = {item.product.product_id: item.product.record_hash for item in result.products}
        explanation = None
        currencies = state["product_service"].config.currency_minor_units
        if result.products:
            facts = render_products(result, names, currency_minor_units=currencies)
            prompt = json.dumps({
                "user_profile": state["step_analysis_data"].user_profile.model_dump(),
                "approved_products": facts.model_dump(),
            })
            try:
                response = await asyncio.wait_for(
                    self.agent.invoke_async(prompt, invocation_state=state), timeout=EXPLANATION_DEADLINE_SECONDS,
                )
                if response.stop_reason == "guardrail_intervened":
                    raise AnalysisFailure("GUARDRAIL_BLOCKED")
                explanation = ProductExplanations.model_validate(response.structured_output)
                # A model subset, extra ID or reordered list is discarded, never followed.
                render_products(result, names, explanation, explanation_hashes=hashes, currency_minor_units=currencies)
            except AnalysisFailure:
                raise  # Guardrail decisions remain terminal.
            except Exception:
                logger.warning("Product explanation unavailable for %s; using factual text", self.id)
                explanation = None
        state["product_explanations"][self.id] = explanation
        state["explanation_hashes"][self.id] = hashes
        output = render_products(result, names, explanation, explanation_hashes=hashes, currency_minor_units=currencies)
        state["products_outputs"][self.id] = output
        return completed(self.id, output)
