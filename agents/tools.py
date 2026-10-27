"""Bounded ingredient discovery. Product selection has no model-callable tool."""

import json
import logging
from threading import Lock

from strands import ToolContext, tool

logger = logging.getLogger(__name__)
_discovery_state_lock = Lock()


def _lookup(step_name, context, operation):
    state = context.invocation_state
    node_id = context.agent.name
    if node_id != f"ingredients_{step_name}":
        raise ValueError("Ingredient lookup belongs to another node")
    # Strands' default executor runs tools concurrently. Only the small state
    # transition is locked; metadata requests remain concurrent and bounded.
    with _discovery_state_lock:
        counts = state.setdefault("discovery_calls", {})
        counts[node_id] = ticket = counts.get(node_id, 0) + 1
        if ticket > 3:
            state.setdefault("tool_errors", {})[node_id] = "discovery_limit"
            raise ValueError("At most three discovery calls per ingredient step")
    service = state["product_service"]
    try:
        response = operation(service.metadata, service.config)
        with _discovery_state_lock:
            successes = state.setdefault("discovery_successes", {})
            successes[node_id] = max(successes.get(node_id, 0), ticket)
            if counts[node_id] <= 3 and ticket >= state.setdefault("discovery_failures", {}).get(node_id, 0):
                state.setdefault("tool_errors", {}).pop(node_id, None)
        return json.dumps(response)
    except Exception:
        with _discovery_state_lock:
            failures = state.setdefault("discovery_failures", {})
            failures[node_id] = max(failures.get(node_id, 0), ticket)
            if counts[node_id] <= 3 and ticket > state.setdefault("discovery_successes", {}).get(node_id, 0):
                state.setdefault("tool_errors", {})[node_id] = "catalog_unavailable"
        logger.exception("Ingredient discovery failed for %s", node_id)
        # Never place database diagnostics in model context.
        return json.dumps({"error": "Ingredient discovery is temporarily unavailable"})


@tool(context=True)
def get_available_ingredients_for_step(step_name: str, tool_context: ToolContext) -> str:
    """Return up to 30 common ingredient IDs as an advisory category summary.

    The list is not exhaustive. Use resolve_ingredient_names for other exact
    identities. An empty summary is valid and does not prove an empty catalog.

    Args:
        step_name: Your assigned routine category.
        tool_context: Injected tool context.
    """
    return _lookup(step_name, tool_context, lambda metadata, config: metadata.summary(step_name, config))


@tool(context=True)
def resolve_ingredient_names(
    step_name: str, names: list[str], tool_context: ToolContext,
) -> str:
    """Look up 1–20 exact ingredient names or reviewed same-identity aliases.

    Unresolved or ambiguous names cannot be selected. Similar names, derivatives,
    and related vitamins are not automatically equivalent.

    Args:
        step_name: Your assigned routine category.
        names: Exact names to resolve, at most 20.
        tool_context: Injected tool context.
    """
    return _lookup(
        step_name, tool_context,
        lambda metadata, config: {"ingredients": metadata.resolve_names(tuple(names), config.taxonomy_version)},
    )
