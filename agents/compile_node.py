"""CompileNode — deterministic graph node that assembles the final routine.

This node runs at the end of Phase 2 (prescription) after all parallel
ingredient/product chains complete. It reads their structured Pydantic
outputs from invocation_state and stitches them into a single
CompiledRoutine JSON. No LLM is involved — the assembly is purely
deterministic.

Flow:
    ingredients_{step} → products_{step} ──┐
    ingredients_{step} → products_{step} ──┼── CompileNode → CompiledRoutine JSON
    ingredients_{step} → products_{step} ──┘
"""

import logging
from typing import Any

from strands.agent.agent_result import AgentResult
from strands.multiagent.base import (
    MultiAgentBase,
    MultiAgentResult,
    NodeResult,
    Status,
)
from strands.types.content import ContentBlock, Message
from strands.types.event_loop import Metrics, Usage

from .models import (
    CompiledRoutine,
    CompiledStep,
    IngredientsAnalysisOutput,
    ProductAnalysisOutput,
    RoutineStep,
    StepAnalysisResult,
)
from .catalog_binding import bind_products

logger = logging.getLogger(__name__)


class CompileNode(MultiAgentBase):
    """Deterministic node that assembles structured outputs into CompiledRoutine JSON.

    Reads IngredientsAnalysisOutput and ProductAnalysisOutput Pydantic models
    from invocation_state (populated by the orchestrator as nodes complete).
    Rejects unresolved tool failures and missing or mismatched step outputs.
    """

    def __init__(self) -> None:
        super().__init__()
        self.id = "compile"

    async def invoke_async(
        self,
        task: Any,
        invocation_state: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> MultiAgentResult:
        """Read structured outputs from invocation_state and assemble CompiledRoutine."""
        invocation_state = invocation_state or {}

        errors = invocation_state.get("tool_errors", {})
        if errors:
            failed_nodes = ", ".join(sorted(errors))
            raise ValueError(f"Catalog lookup failed for: {failed_nodes}")

        plan = StepAnalysisResult.model_validate(
            invocation_state.get("step_analysis_data")
        )

        # Read structured outputs from invocation_state
        ingredients_outputs: dict[str, IngredientsAnalysisOutput] = (
            invocation_state.get("ingredients_outputs", {})
        )
        products_outputs: dict[str, ProductAnalysisOutput] = invocation_state.get(
            "products_outputs", {}
        )

        logger.info(
            "CompileNode: %d ingredients outputs, %d products outputs",
            len(ingredients_outputs),
            len(products_outputs),
        )

        compiled_steps = self._build_steps(
            plan.routine_steps, ingredients_outputs, products_outputs,
            invocation_state.get("trusted_products", {}),
        )

        routine = CompiledRoutine(
            user_profile=plan.user_profile, routine_steps=compiled_steps
        )
        routine_json = routine.model_dump_json()

        logger.info("CompileNode produced routine with %d steps", len(compiled_steps))

        # Wrap in AgentResult → NodeResult → MultiAgentResult
        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(
                role="assistant", content=[ContentBlock(text=routine_json)]
            ),
            metrics=None,
            state={},
        )

        node_result = NodeResult(
            result=agent_result,
            execution_time=0,
            status=Status.COMPLETED,
            accumulated_usage=Usage(inputTokens=0, outputTokens=0, totalTokens=0),
            accumulated_metrics=Metrics(latencyMs=0),
            execution_count=1,
        )

        return MultiAgentResult(
            status=Status.COMPLETED,
            results={self.id: node_result},
            accumulated_usage=Usage(inputTokens=0, outputTokens=0, totalTokens=0),
            accumulated_metrics=Metrics(latencyMs=0),
            execution_count=1,
        )

    def _build_steps(
        self,
        steps: list[RoutineStep],
        ingredients_outputs: dict[str, IngredientsAnalysisOutput],
        products_outputs: dict[str, ProductAnalysisOutput],
        trusted_products: dict,
    ) -> list[CompiledStep]:
        """Build CompiledStep list from structured outputs.

        Args:
            steps: Ordered, validated routine steps from step_analysis.
            ingredients_outputs: Keyed by node_id (e.g. "ingredients_Cleanser").
            products_outputs: Keyed by node_id (e.g. "products_Cleanser").

        Returns:
            List of fully populated CompiledStep objects.
        """
        compiled: list[CompiledStep] = []

        for step in steps:
            step_name = step.step_name
            ing_output = ingredients_outputs.get(f"ingredients_{step_name}")
            prod_output = products_outputs.get(f"products_{step_name}")
            if ing_output is None or prod_output is None:
                raise ValueError(f"Missing recommendation output for {step_name}")
            if ing_output.step_name != step_name or prod_output.step_name != step_name:
                raise ValueError(f"Recommendation output does not match step {step_name}")
            if not ing_output.key_ingredients or not prod_output.top_recommendations:
                raise ValueError(f"No recommendations produced for {step_name}")

            compiled.append(
                CompiledStep(
                    step_name=step_name,
                    when=step.when,
                    description=step.justification,
                    why_for_you=step.why_this_step_for_you,
                    ingredients=ing_output.key_ingredients,
                    products=bind_products(prod_output, f"products_{step_name}", trusted_products).top_recommendations,
                )
            )

        return compiled
