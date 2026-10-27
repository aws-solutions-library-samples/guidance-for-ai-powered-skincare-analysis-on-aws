"""Discovery is advisory, bounded, node-scoped, and independent of selection."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agents.tools import get_available_ingredients_for_step, resolve_ingredient_names
from tests.search_fixtures import configuration


@pytest.fixture
def context():
    service = Mock()
    service.config = configuration()
    return SimpleNamespace(
        invocation_state={"product_service": service},
        agent=SimpleNamespace(name="ingredients_Cleanser"),
    )


def test_failure_then_retry_clears_only_its_error(context):
    metadata = context.invocation_state["product_service"].metadata
    metadata.summary.side_effect = [
        RuntimeError("private database details"),
        {"ingredients": [], "advisory": True},
    ]
    context.invocation_state["tool_errors"] = {"ingredients_Serum": "unavailable"}
    failed = json.loads(get_available_ingredients_for_step("Cleanser", context))
    assert "error" in failed and "private" not in failed["error"]
    success = json.loads(get_available_ingredients_for_step("Cleanser", context))
    assert success == {"ingredients": [], "advisory": True}
    assert context.invocation_state["tool_errors"] == {"ingredients_Serum": "unavailable"}


def test_exact_lookup_allows_ingredients_outside_common_summary(context):
    metadata = context.invocation_state["product_service"].metadata
    metadata.summary.return_value = {"ingredients": [], "advisory": True}
    metadata.resolve_names.return_value = [{
        "input": "Rare ingredient", "status": "resolved", "ingredient_id": "ing-rare",
    }]
    get_available_ingredients_for_step("Cleanser", context)
    result = json.loads(resolve_ingredient_names("Cleanser", ["Rare ingredient"], context))
    assert result["ingredients"][0]["ingredient_id"] == "ing-rare"


def test_fourth_discovery_call_cannot_extend_budget(context):
    metadata = context.invocation_state["product_service"].metadata
    metadata.summary.return_value = {"ingredients": []}
    for _ in range(3):
        get_available_ingredients_for_step("Cleanser", context)
    with pytest.raises(ValueError, match="three"):
        get_available_ingredients_for_step("Cleanser", context)
    assert metadata.summary.call_count == 3
    assert context.invocation_state["tool_errors"]["ingredients_Cleanser"]


def test_other_nodes_category_cannot_be_queried(context):
    with pytest.raises(ValueError, match="another node"):
        get_available_ingredients_for_step("Serum", context)
    context.invocation_state["product_service"].metadata.summary.assert_not_called()


def test_concurrent_completion_cannot_clear_the_three_call_limit(context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from agents.tools import _lookup

    entered, release = Event(), Event()
    def delayed(*args):
        entered.set()
        assert release.wait(timeout=3)
        return {}
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(_lookup, "Cleanser", context, delayed)
        assert entered.wait(timeout=3)
        _lookup("Cleanser", context, lambda *args: {})
        _lookup("Cleanser", context, lambda *args: {})
        try:
            with pytest.raises(ValueError, match="three"):
                _lookup("Cleanser", context, lambda *args: {})
        finally:
            release.set()
        assert first.result() == "{}"
    state = context.invocation_state
    assert state["discovery_calls"]["ingredients_Cleanser"] == 4
    assert state["tool_errors"]["ingredients_Cleanser"] == "discovery_limit"
