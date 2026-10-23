"""Two-phase Graph orchestrator for the skincare recommendation pipeline.

Phase 1 — Diagnose (static):  skin_analysis → step_analysis
Phase 2 — Prescribe (dynamic): N × ingredients_{step} → N × products_{step} → compile

Graph edges carry agent context; invocation state carries validated outputs
to the deterministic compiler. No global mutable state.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

from strands.multiagent import GraphBuilder
from strands.multiagent.base import Status
from strands.multiagent.graph import Graph, GraphState
from strands.types.content import ContentBlock

from catalog import load_catalog

from .ingredients_analysis_agent import create_ingredients_agent
from .models import RoutineStep, StepAnalysisResult
from .product_agent import create_product_agent
from .product_repository import ProductService
from .skin_analysis_agent import create_skin_analysis_agent
from .step_analysis_agent import create_step_analysis_agent
from .compile_node import CompileNode
from .errors import AnalysisFailure
from .catalog_binding import bind_products

logger = logging.getLogger(__name__)


def _all_dependencies_complete(required_nodes: list[str]):
    """Factory for AND-condition: compile waits for ALL product nodes (prescribe phase).

    Args:
        required_nodes: List of node IDs that must all be COMPLETED.

    Returns:
        Callable[[GraphState], bool] for use as a conditional edge.
    """

    def check_all_complete(state: GraphState) -> bool:
        return all(
            node_id in state.results
            and state.results[node_id].status == Status.COMPLETED
            for node_id in required_nodes
        )

    return check_all_complete


class Orchestrator:
    """Coordinates specialized skincare agents via two-phase Graph execution.

    Phase 1 — Diagnose: skin_analysis → step_analysis (sequential, static graph)
    Phase 2 — Prescribe: N parallel ingredient/product chains → compile (dynamic graph)
    """

    def __init__(self) -> None:
        self.product_service = ProductService()

    async def run(self, image_bytes_list: list[bytes]) -> AsyncIterator[dict]:
        """Execute two-phase graph, yielding stream_async events.

        Args:
            image_bytes_list: Raw JPEG image bytes for skin analysis.

        Yields:
            Dict events from stream_async (multiagent_node_start,
            multiagent_node_stop, multiagent_result, etc.).

        Raises:
            RuntimeError: If the products database is empty.
        """
        if not self.product_service.has_products():
            logger.error("Product database is empty")
            raise AnalysisFailure("SERVICE_UNAVAILABLE")

        invocation_state: dict[str, Any] = {
            "product_service": self.product_service,
            "tool_errors": {},
            "trusted_products": {},
        }

        # --- Diagnose: Static graph (skin_analysis → step_analysis) ---
        phase1 = self._build_diagnose_graph()
        content_blocks = self._build_image_input(image_bytes_list)

        phase1_result = None
        async for event in phase1.stream_async(
            content_blocks, invocation_state=invocation_state
        ):
            if event.get("type") == "multiagent_result":
                phase1_result = event["result"]
            yield event

        if phase1_result is None:
            raise RuntimeError("Diagnose graph did not produce a result")

        # Parse step_analysis output
        step_analysis_result = self._parse_step_analysis(phase1_result)
        steps = step_analysis_result.routine_steps
        logger.info(
            "Diagnose phase complete: %d routine steps identified",
            len(steps),
        )

        # Store step_analysis data in invocation_state for CompileNode
        invocation_state["step_analysis_data"] = step_analysis_result

        # --- Prescribe: Dynamic graph (ingredients → products → compile) ---
        phase2 = self._build_prescribe_graph(steps)
        task = self._build_prescribe_task(step_analysis_result)

        # Dicts to collect structured outputs for CompileNode
        invocation_state["ingredients_outputs"] = {}
        invocation_state["products_outputs"] = {}

        async for event in phase2.stream_async(task, invocation_state=invocation_state):
            # Capture structured outputs as nodes complete
            if event.get("type") == "multiagent_node_stop":
                node_id = event["node_id"]
                node_result = event.get("node_result")
                if node_result and hasattr(node_result.result, "structured_output"):
                    so = node_result.result.structured_output
                    if so is not None:
                        if node_id.startswith("ingredients_"):
                            invocation_state["ingredients_outputs"][node_id] = so
                        elif node_id.startswith("products_"):
                            so = bind_products(so, node_id, invocation_state["trusted_products"])
                            node_result.result.structured_output = so
                            # Replace raw model product text too, including later graph summaries.
                            node_result.result.message = {
                                "role": "assistant", "content": [{"text": so.model_dump_json()}],
                            }
                            invocation_state["products_outputs"][node_id] = so
            yield event

    def _build_diagnose_graph(self) -> Graph:
        """Build the static Diagnose graph: skin_analysis → step_analysis."""
        builder = GraphBuilder()
        builder.add_node(create_skin_analysis_agent(), "skin_analysis")
        builder.add_node(create_step_analysis_agent(), "step_analysis")
        builder.add_edge("skin_analysis", "step_analysis")
        builder.set_entry_point("skin_analysis")
        builder.set_execution_timeout(300)
        return builder.build()

    def _build_prescribe_graph(self, steps: list[RoutineStep]) -> Graph:
        """Build the dynamic Prescribe graph from diagnose output.

        Creates N parallel chains: ingredients_{step} → products_{step},
        all converging on a single compile node.

        Args:
            steps: Routine steps from Phase 1 step_analysis output.

        Returns:
            Configured Graph ready for execution.
        """
        available_categories = set(load_catalog().categories)
        invalid_steps = [
            step.step_name for step in steps
            if step.step_name not in available_categories
        ]
        if invalid_steps:
            raise ValueError(f"Routine includes unknown catalog categories: {invalid_steps}")

        builder = GraphBuilder()

        # Add ingredient + product node pairs per step
        for step in steps:
            name = step.step_name
            builder.add_node(create_ingredients_agent(name), f"ingredients_{name}")
            builder.add_node(create_product_agent(name), f"products_{name}")
            builder.add_edge(f"ingredients_{name}", f"products_{name}")

        # Add compile node with conditional edges (wait for ALL products)
        compile_node = CompileNode()
        builder.add_node(compile_node, "compile")

        product_node_ids = [f"products_{s.step_name}" for s in steps]
        all_done = _all_dependencies_complete(product_node_ids)
        for pid in product_node_ids:
            builder.add_edge(pid, "compile", condition=all_done)

        builder.set_execution_timeout(600)
        return builder.build()

    def _parse_step_analysis(self, graph_result: Any) -> StepAnalysisResult:
        """Extract StepAnalysisResult from Phase 1 graph result.

        Reads the validated Pydantic model from structured_output,
        set by step_analysis agent's structured_output_model.

        Args:
            graph_result: GraphResult from Phase 1 execution.

        Returns:
            Parsed StepAnalysisResult.

        Raises:
            ValueError: If step_analysis output cannot be parsed.
        """
        node_result = graph_result.results.get("step_analysis")
        if not node_result:
            raise ValueError("step_analysis node not found in Phase 1 results")

        result_obj = node_result.result
        if hasattr(result_obj, "structured_output") and result_obj.structured_output:
            return StepAnalysisResult.model_validate(result_obj.structured_output)

        raise ValueError("step_analysis node did not produce structured_output")

    @staticmethod
    def _detect_image_format(image_bytes: bytes) -> str:
        """Detect image format from magic bytes.

        Args:
            image_bytes: Raw image bytes.

        Returns:
            Format string compatible with Bedrock Converse API:
            'jpeg', 'png', 'gif', or 'webp'.

        Raises:
            ValueError: If the format cannot be detected or is unsupported.
        """
        if image_bytes[:3] == b"\xff\xd8\xff":
            return "jpeg"
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "webp"
        if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
            return "gif"
        raise ValueError(
            f"Unsupported image format (magic bytes: {image_bytes[:12].hex()})"
        )

    def _build_image_input(self, image_bytes_list: list[bytes]) -> list[ContentBlock]:
        """Build multi-modal ContentBlock list for skin_analysis entry node.

        Detects actual image format from magic bytes instead of assuming JPEG.
        Bedrock Converse supports: jpeg, png, gif, webp.

        Args:
            image_bytes_list: Raw image bytes (any supported format).

        Returns:
            List of ContentBlocks with image blocks + text prompt.
        """
        blocks: list[ContentBlock] = []
        for i, img_bytes in enumerate(image_bytes_list):
            fmt = self._detect_image_format(img_bytes)
            logger.info("Image %d: format=%s, size=%d bytes", i, fmt, len(img_bytes))
            blocks.append(
                ContentBlock(image={"format": fmt, "source": {"bytes": img_bytes}})
            )
        blocks.append(
            ContentBlock(
                text=(
                    f"Analyze these {len(image_bytes_list)} skin images "
                    "and generate a comprehensive skin profile."
                )
            )
        )
        return blocks

    def _build_prescribe_task(self, step_analysis: StepAnalysisResult) -> str:
        """Build the text task for Prescribe graph entry nodes.

        Each ingredients_* entry node receives the full step_analysis context
        so it knows the user profile and which step to analyze.

        Args:
            step_analysis: Parsed result from Phase 1.

        Returns:
            Text task string with user profile and step details.
        """
        # Tool/role instructions already live in each agent's system prompt.
        # Keep this guarded message as data: the former imperative suffix
        # triggered PROMPT_ATTACK even with an otherwise allowed routine.
        return (
            f"User skin analysis and routine plan:\n\n"
            f"{step_analysis.model_dump_json(indent=2)}"
        )
