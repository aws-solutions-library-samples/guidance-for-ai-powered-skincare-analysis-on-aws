"""Offline application pipeline: request → orchestration → compilation → SSE.

Only the external agent graphs and product table are replaced. The application
entrypoint, state transfer, output models, compiler, and serializer run normally.
"""

import asyncio
import base64
import json
import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from strands.agent.agent_result import AgentResult
from strands.multiagent.base import MultiAgentResult, NodeResult, Status

import agentcore_entrypoint as entrypoint
from agents.compile_node import CompileNode
from agents.models import StepAnalysisResult
from agents.orchestrator import Orchestrator, _all_dependencies_complete
from tests.live_sse import read_events, validate_events


def node_result(output=None):
    return NodeResult(
        result=AgentResult(
            stop_reason="end_turn", message={"role": "assistant", "content": []},
            metrics=None, state={}, structured_output=output,
        ),
        status=Status.COMPLETED,
    )


async def collect(payload):
    return [event async for event in entrypoint.invoke(payload, object())]


@pytest.fixture
def pipeline(monkeypatch, routine_state):
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.product_service = Mock()
    orchestrator.product_service.has_products.return_value = True
    plan = StepAnalysisResult.model_validate(routine_state["step_analysis_data"])
    skin = Mock()
    skin.model_dump.return_value = {"skin_type": "Dry", "concerns": ["dryness"]}

    class DiagnoseGraph:
        async def stream_async(self, task, invocation_state):
            with Image.open(io.BytesIO(task[0]["image"]["source"]["bytes"])) as image:
                assert image.format == "JPEG" and image.size == (64, 64)
            results = {}
            for name, output in (("skin_analysis", skin), ("step_analysis", plan)):
                yield {"type": "multiagent_node_start", "node_id": name}
                results[name] = node_result(output)
                yield {"type": "multiagent_node_stop", "node_id": name, "node_result": results[name]}
            yield {"type": "multiagent_result", "result": MultiAgentResult(status=Status.COMPLETED, results=results)}

    class PrescribeGraph:
        async def stream_async(self, task, invocation_state):
            # Preserve the entire plan as data; agent instructions belong in
            # system prompts, not appended to the guarded graph input.
            payload = task.removeprefix("User skin analysis and routine plan:\n\n")
            assert StepAnalysisResult.model_validate_json(payload) == plan
            invocation_state["trusted_products"] = routine_state["trusted_products"]
            assert StepAnalysisResult.model_validate(invocation_state["step_analysis_data"]) == plan
            assert invocation_state["product_service"] is orchestrator.product_service
            results = {}
            # Finish chains in reverse plan order to check deterministic assembly.
            for step in reversed(plan.routine_steps):
                for prefix in ("ingredients", "products"):
                    name = f"{prefix}_{step.step_name}"
                    yield {"type": "multiagent_node_start", "node_id": name}
                    output = routine_state[f"{prefix}_outputs"][name]
                    results[name] = node_result(output)
                    yield {"type": "multiagent_node_stop", "node_id": name, "node_result": results[name]}
            yield {"type": "multiagent_node_start", "node_id": "compile"}
            compiled = await CompileNode().invoke_async(task, invocation_state)
            results["compile"] = NodeResult(result=compiled, status=Status.COMPLETED)
            yield {"type": "multiagent_node_stop", "node_id": "compile", "node_result": results["compile"]}
            yield {"type": "multiagent_result", "result": MultiAgentResult(status=Status.COMPLETED, results=results)}

    monkeypatch.setattr(orchestrator, "_build_diagnose_graph", lambda: DiagnoseGraph())
    monkeypatch.setattr(orchestrator, "_build_prescribe_graph", lambda steps: PrescribeGraph())
    monkeypatch.setattr(entrypoint, "Orchestrator", lambda: orchestrator)
    return orchestrator


@pytest.fixture
def request_payload(valid_image):
    return {"job_id": "offline-job", "images": [valid_image]}


def test_request_to_final_wire_result(pipeline, request_payload):
    events = asyncio.run(collect(request_payload))
    assert len([event for event in events if event["type"] == "multiagent_result"]) == 2
    assert validate_events(events) == []
    assert json.loads(json.dumps(events)) == events


def test_untrusted_product_fields_are_replaced_before_any_public_event(pipeline, request_payload, routine_state):
    for output in routine_state["products_outputs"].values():
        for product in output.top_recommendations:
            product.name = "FABRICATED-NAME"
            product.price = "FABRICATED-PRICE"
            product.image_url = "https://attacker.invalid/collect"
    events = asyncio.run(collect(request_payload))
    assert validate_events(events) == []
    wire = json.dumps(events)
    assert "FABRICATED-" not in wire and "attacker.invalid" not in wire
    assert "/products/example.jpg" in wire


def test_unknown_product_id_never_reaches_public_node_output(pipeline, request_payload, routine_state):
    routine_state["products_outputs"]["products_Sunscreen"].top_recommendations[0].product_id = "fabricated-id"
    events = asyncio.run(collect(request_payload))
    assert events[-1]["code"] == "INVALID_RESPONSE"
    assert "fabricated-id" not in json.dumps(events)
    assert not any(event.get("node_id") == "compile" for event in events)


def test_agentcore_http_adapter_ping_stream_and_application_error(pipeline, request_payload):
    """Exercise the actual locked AgentCore/Starlette ASGI adapter in memory."""
    from starlette.testclient import TestClient

    with TestClient(entrypoint.app) as client:
        ping = client.get("/ping")
        assert ping.status_code == 200
        assert ping.json()["status"].upper() == "HEALTHY"
        response = client.post("/invocations", json=request_payload)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.content.startswith(b"data: ")
        events = read_events(response)
        assert validate_events(events) == []
        assert events[-1]["type"] == "multiagent_result"
        failed = client.post("/invocations", json={})
        assert failed.status_code == 200  # Application errors travel over SSE.
        error_events = read_events(failed)
        assert [event["type"] for event in error_events] == ["error"]
        assert error_events[0]["message"]


def test_agentcore_http_adapter_rejects_invalid_json_before_pipeline(pipeline):
    from starlette.testclient import TestClient

    with TestClient(entrypoint.app) as client:
        response = client.post(
            "/invocations", content="not-json", headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
    pipeline.product_service.has_products.assert_not_called()


@pytest.mark.parametrize("payload", [
    {}, {"job_id": "a", "images": []}, {"job_id": "", "images": ["image"]},
    {"job_id": "a", "images": "not-a-list"}, {"job_id": "a", "images": ["not base64!"]},
    {"job_id": "a", "images": [base64.b64encode(b"not an image").decode()]},
    {"job_id": "unsafe\nidentifier", "images": ["image"]},
])
def test_invalid_requests_return_error_without_constructing_runtime(monkeypatch, payload):
    factory = Mock(side_effect=AssertionError("Must validate first"))
    monkeypatch.setattr(entrypoint, "Orchestrator", factory)
    events = asyncio.run(collect(payload))
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["code"] == "INVALID_INPUT"
    factory.assert_not_called()


@pytest.mark.parametrize("failure,code", [
    (RuntimeError("catalog unavailable"), "ANALYSIS_FAILED"),
    (ValueError("invalid model output"), "INVALID_RESPONSE"),
])
def test_runtime_failures_become_error_events(monkeypatch, request_payload, failure, code):
    class FailedOrchestrator:
        async def run(self, images):
            raise failure
            yield  # Preserve the real runtime's async-generator interface.

    monkeypatch.setattr(entrypoint, "Orchestrator", FailedOrchestrator)
    events = asyncio.run(collect(request_payload))
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == code
    assert events[-1]["request_id"] == request_payload["job_id"]
    assert str(failure) not in events[-1]["message"]


def test_missing_compile_cannot_end_as_success(monkeypatch, request_payload):
    class IncompleteOrchestrator:
        async def run(self, images):
            yield {"type": "multiagent_result", "result": MultiAgentResult(status=Status.COMPLETED)}

    monkeypatch.setattr(entrypoint, "Orchestrator", IncompleteOrchestrator)
    assert asyncio.run(collect(request_payload))[-1]["type"] == "error"


def test_empty_catalog_stops_before_model_graphs(pipeline, request_payload):
    pipeline.product_service.has_products.return_value = False
    events = asyncio.run(collect(request_payload))
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["code"] == "SERVICE_UNAVAILABLE"


def test_compile_gate_requires_every_successful_product():
    ready = _all_dependencies_complete(["products_Cleanser", "products_Sunscreen"])
    state = SimpleNamespace(results={"products_Cleanser": SimpleNamespace(status=Status.COMPLETED)})
    assert not ready(state)
    state.results["products_Sunscreen"] = SimpleNamespace(status=Status.FAILED)
    assert not ready(state)
    state.results["products_Sunscreen"].status = Status.COMPLETED
    assert ready(state)


def test_unknown_catalog_step_is_rejected_before_building_graph(routine_state):
    orchestrator = Orchestrator.__new__(Orchestrator)
    plan = StepAnalysisResult.model_validate(routine_state["step_analysis_data"])
    plan.routine_steps[0].step_name = "Not a catalog category"
    with pytest.raises(ValueError, match="(?i)(category|catalog|unknown|unsupported)"):
        orchestrator._build_prescribe_graph(plan.routine_steps)
