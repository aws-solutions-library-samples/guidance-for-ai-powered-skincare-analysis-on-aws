"""Test that the entrypoint produces valid, JSON-serializable SSE events.

Run locally without AWS credentials:
    uv run pytest tests/unit/test_sse_streaming.py -v

Validates:
1. _serialize_event produces JSON-safe dicts for all event types
2. structured_output from Pydantic models is included in serialized events
3. The full event flow matches what the frontend expects
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentcore_entrypoint import _serialize_event


# --- Minimal fakes mimicking Strands SDK types ---


class Status(Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class FakeAgentResult:
    message: dict = field(default_factory=dict)
    stop_reason: str = "end_turn"
    structured_output: Any = None

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "stop_reason": self.stop_reason,
        }


@dataclass
class FakeNodeResult:
    result: Any = None
    status: Status = Status.COMPLETED
    accumulated_usage: dict = field(default_factory=dict)
    accumulated_metrics: dict = field(default_factory=dict)
    execution_time: float = 1.0
    interrupts: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "result": self.result.to_dict() if hasattr(self.result, "to_dict") else str(self.result),
            "status": self.status.value,
            "execution_time": self.execution_time,
        }


class FakePydanticModel:
    """Mimics a Pydantic BaseModel with model_dump()."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self) -> dict:
        return self._data


# --- Tests ---


class TestSerializeNodeStart:
    def test_basic_node_start(self):
        event = {"type": "multiagent_node_start", "node_id": "skin_analysis"}
        result = _serialize_event(event)

        assert result == {"type": "multiagent_node_start", "node_id": "skin_analysis"}
        json.dumps(result)  # Must be JSON-serializable

    def test_ingredients_node_start(self):
        event = {"type": "multiagent_node_start", "node_id": "ingredients_cleanser"}
        result = _serialize_event(event)

        assert result["node_id"] == "ingredients_cleanser"
        json.dumps(result)


class TestSerializeNodeStop:
    def test_node_stop_without_structured_output(self):
        agent_result = FakeAgentResult(
            message={"content": [{"text": "done"}]},
        )
        node_result = FakeNodeResult(result=agent_result)
        event = {
            "type": "multiagent_node_stop",
            "node_id": "skin_analysis",
            "node_result": node_result,
        }

        result = _serialize_event(event)
        assert result["type"] == "multiagent_node_stop"
        assert result["node_id"] == "skin_analysis"
        assert "structured_output" not in result["node_result"]["result"]
        json.dumps(result)

    def test_node_stop_with_structured_output(self):
        skin_profile = FakePydanticModel({
            "skin_type": "Combination",
            "age": "25-32",
            "concerns": ["dehydration", "texture"],
            "current_condition": "Mildly dehydrated",
            "recommended_goals": "Hydration and texture improvement",
            "skin_metrics": {
                "skin_health": 78,
                "hydration": 62,
                "texture": 70,
                "pore_size": 75,
                "elasticity": 85,
                "radiance": 68,
            },
            "strengths": ["Good elasticity", "Even skin tone"],
        })
        agent_result = FakeAgentResult(
            message={"content": [{"text": "analysis complete"}]},
            structured_output=skin_profile,
        )
        node_result = FakeNodeResult(result=agent_result)
        event = {
            "type": "multiagent_node_stop",
            "node_id": "skin_analysis",
            "node_result": node_result,
        }

        result = _serialize_event(event)
        so = result["node_result"]["result"]["structured_output"]
        assert so["skin_type"] == "Combination"
        assert so["skin_metrics"]["hydration"] == 62
        json.dumps(result)

    def test_ingredients_node_stop(self):
        ingredients = FakePydanticModel({
            "step_name": "cleanser",
            "key_ingredients": [
                {"name": "Niacinamide", "benefit": "Pore control", "why_for_you": "Targets oiliness", "usage": "AM/PM"},
            ],
            "analysis_notes": "Gentle cleansing focus",
        })
        agent_result = FakeAgentResult(structured_output=ingredients)
        node_result = FakeNodeResult(result=agent_result)
        event = {
            "type": "multiagent_node_stop",
            "node_id": "ingredients_cleanser",
            "node_result": node_result,
        }

        result = _serialize_event(event)
        so = result["node_result"]["result"]["structured_output"]
        assert so["step_name"] == "cleanser"
        assert len(so["key_ingredients"]) == 1
        json.dumps(result)

    def test_products_node_stop(self):
        products = FakePydanticModel({
            "step_name": "moisturizer",
            "top_recommendations": [
                {
                    "name": "CeraVe Moisturizing Cream",
                    "price": "$16.99",
                    "match_score": "85%",
                    "image_url": "https://example.com/img.jpg",
                    "matched_ingredients": ["Ceramides", "Hyaluronic Acid"],
                    "why_for_you": "Restores barrier",
                    "usage_tip": "Apply on damp skin",
                },
            ],
        })
        agent_result = FakeAgentResult(structured_output=products)
        node_result = FakeNodeResult(result=agent_result)
        event = {
            "type": "multiagent_node_stop",
            "node_id": "products_moisturizer",
            "node_result": node_result,
        }

        result = _serialize_event(event)
        so = result["node_result"]["result"]["structured_output"]
        assert so["top_recommendations"][0]["name"] == "CeraVe Moisturizing Cream"
        json.dumps(result)


class TestSerializeMultiagentResult:
    def test_multiagent_result_with_mock(self):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"results": {"compile": {"status": "COMPLETED"}}}
        event = {"type": "multiagent_result", "result": mock_result}

        result = _serialize_event(event)
        assert result["type"] == "multiagent_result"
        assert result["result"]["results"]["compile"]["status"] == "COMPLETED"
        json.dumps(result)


class TestSerializeErrorEvent:
    def test_untyped_errors_do_not_leak_internal_messages(self):
        event = {"type": "error", "message": "Something went wrong"}
        result = _serialize_event(event)
        assert result["type"] == "error"
        assert result["code"] == "ANALYSIS_FAILED"
        assert result["message"] != "Something went wrong"
        json.dumps(result)


class TestFullEventSequence:
    """Validates the complete event sequence the frontend expects."""

    def test_expected_event_flow(self):
        """Simulate a minimal pipeline and verify all events serialize."""
        events = [
            {"type": "multiagent_node_start", "node_id": "skin_analysis"},
            {
                "type": "multiagent_node_stop",
                "node_id": "skin_analysis",
                "node_result": FakeNodeResult(
                    result=FakeAgentResult(
                        structured_output=FakePydanticModel({
                            "skin_type": "Oily",
                            "age": "25-32",
                            "concerns": ["acne"],
                            "current_condition": "Active breakouts",
                            "recommended_goals": "Clear skin",
                            "skin_metrics": {"skin_health": 60, "hydration": 70, "texture": 55, "pore_size": 50, "elasticity": 80, "radiance": 65},
                            "strengths": ["Good elasticity"],
                        })
                    )
                ),
            },
            {"type": "multiagent_node_start", "node_id": "step_analysis"},
            {
                "type": "multiagent_node_stop",
                "node_id": "step_analysis",
                "node_result": FakeNodeResult(
                    result=FakeAgentResult(
                        structured_output=FakePydanticModel({
                            "user_profile": {"skin_type": "Oily", "age": "25-32", "concerns": ["acne"], "routine_rationale": "Focus on oil control"},
                            "routine_steps": [
                                {"step_name": "Cleanser", "justification": "Remove oil", "why_this_step_for_you": "Controls breakouts", "when": "Morning & Evening"},
                            ],
                            "routine_summary": {"total_steps": 1, "benefits": ["Oil control"], "usage_notes": ["Be gentle"]},
                        })
                    )
                ),
            },
            {"type": "multiagent_node_start", "node_id": "ingredients_Cleanser"},
            {
                "type": "multiagent_node_stop",
                "node_id": "ingredients_Cleanser",
                "node_result": FakeNodeResult(
                    result=FakeAgentResult(
                        structured_output=FakePydanticModel({
                            "step_name": "Cleanser",
                            "key_ingredients": [{"name": "Salicylic Acid", "benefit": "Unclogs pores", "why_for_you": "Targets acne", "usage": "AM/PM"}],
                            "analysis_notes": "BHA for oily skin",
                        })
                    )
                ),
            },
            {"type": "multiagent_node_start", "node_id": "products_Cleanser"},
            {
                "type": "multiagent_node_stop",
                "node_id": "products_Cleanser",
                "node_result": FakeNodeResult(
                    result=FakeAgentResult(
                        structured_output=FakePydanticModel({
                            "step_name": "Cleanser",
                            "top_recommendations": [
                                {"name": "CeraVe SA Cleanser", "price": "$12.99", "match_score": "92%", "image_url": "", "matched_ingredients": ["Salicylic Acid"], "why_for_you": "Gentle BHA", "usage_tip": "Massage for 60s"},
                            ],
                        })
                    )
                ),
            },
        ]

        serialized = [_serialize_event(e) for e in events]
        for s in serialized:
            json_str = json.dumps(s)
            assert json_str  # Non-empty
            reparsed = json.loads(json_str)
            assert reparsed["type"] in (
                "multiagent_node_start",
                "multiagent_node_stop",
                "multiagent_result",
                "error",
            )
