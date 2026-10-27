"""Offline application pipeline: request → orchestration → compilation → SSE.

Only the external agent graphs and product table are replaced. The application
entrypoint, state transfer, output models, compiler, and serializer run normally.
"""

import asyncio
import base64
import json
import io
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import time

import pytest
from PIL import Image
from strands.agent.agent_result import AgentResult
from strands.multiagent.base import MultiAgentResult, NodeResult, Status

import agentcore_entrypoint as entrypoint
from agents.compile_node import CompileNode
from agents.models import StepAnalysisResult, ProductExplanations
from agents.orchestrator import Orchestrator, _all_dependencies_complete
import agents.orchestrator as orchestration
from agents.product_repository import ProductService
from agents.search.catalog import IngredientEntry
from tests.search_fixtures import configuration, engine_response, readiness
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
    metadata, repository, client = Mock(), Mock(), Mock()
    metadata.configuration.return_value = configuration(categories=("Cleanser", "Sunscreen"))
    metadata.readiness.side_effect = lambda *args: readiness(checked_at=time.time())
    metadata.ingredients.return_value = {"ing-a": IngredientEntry(
        ingredient_id="ing-a", display_name="Glycerin", taxonomy_version="fixture-v1",
        review_state="synthetic_fixture", provenance="fixture",
    )}
    records = {
        item.product.product_id: item.product
        for result in routine_state["search_results"].values() for item in result.products
    }
    repository.catalog_id = "fixture"
    repository.get_by_ids.side_effect = lambda ids, budget: {key: records[key] for key in ids if key in records}
    client.transport.max_retries = 0

    def search(**kwargs):
        category = next(
            item["term"]["category_id"] for item in kwargs["body"]["query"]["bool"]["filter"]
            if "category_id" in item.get("term", {})
        )
        selected = [item for item in records.values() if item.category_id == category]
        return engine_response(selected, [1] * len(selected))

    client.search.side_effect = search
    orchestrator.product_service = ProductService(metadata=metadata, repository=repository, client=client)
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

    def ingredient_agent(category):
        return SimpleNamespace(invoke_async=AsyncMock(return_value=node_result(
            routine_state["ingredients_outputs"][f"ingredients_{category}"],
        ).result))

    def product_agent(category):
        # Tests may alter this stand-in model output; the server ignores all facts.
        selected = routine_state["products_outputs"][f"products_{category}"].top_recommendations
        output = ProductExplanations(step_name=category, products=[{
            "product_id": item.product_id, "why_for_you": item.why_for_you, "usage_tip": item.usage_tip,
        } for item in selected])
        return SimpleNamespace(invoke_async=AsyncMock(return_value=node_result(output).result))

    monkeypatch.setattr(orchestrator, "_build_diagnose_graph", lambda: DiagnoseGraph())
    monkeypatch.setattr(orchestration, "create_ingredients_agent", ingredient_agent)
    monkeypatch.setattr(orchestration, "create_product_agent", product_agent)
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


@pytest.mark.parametrize("empty_categories", [("Sunscreen",), ("Cleanser", "Sunscreen")])
def test_v2_mixed_and_all_no_match_finish_through_the_real_graph(pipeline, request_payload, empty_categories):
    original = pipeline.product_service.client.search.side_effect
    def search(**kwargs):
        category = next(item["term"]["category_id"] for item in kwargs["body"]["query"]["bool"]["filter"]
                        if "category_id" in item.get("term", {}))
        return engine_response([]) if category in empty_categories else original(**kwargs)
    pipeline.product_service.client.search.side_effect = search
    events = asyncio.run(collect({**request_payload, "api_version": 2, "preferences": {}}))
    assert not [event for event in events if event["type"] == "error"]
    stop = next(event for event in events if event.get("node_id") == "compile" and event["type"] == "multiagent_node_stop")
    routine = json.loads(stop["node_result"]["result"]["results"]["compile"]["result"]["message"]["content"][0]["text"])
    assert routine["api_version"] == 2
    for step in routine["routine_steps"]:
        assert step["recommendation_status"] == ("no_match" if step["step_name"] in empty_categories else "matched")
        if step["step_name"] in empty_categories:
            assert step["products"] == [] and step["no_match_reason"] == "no_matching_products"
    assert events[-1]["type"] == "multiagent_result"


def test_v1_no_match_returns_a_terminal_domain_error(pipeline, request_payload):
    pipeline.product_service.client.search.side_effect = lambda **kwargs: engine_response([])
    events = asyncio.run(collect(request_payload))
    assert events[-1]["type"] == "error" and events[-1]["code"] == "NO_MATCHING_PRODUCTS"
    assert not any(event.get("node_id") == "compile" and "node_result" in event for event in events)


def test_missing_mandatory_category_stops_before_any_product_query(pipeline, request_payload):
    pipeline.product_service.metadata.configuration.return_value = configuration(categories=("Cleanser", "Sunscreen", "Serum"))
    events = asyncio.run(collect({**request_payload, "api_version": 2, "preferences": {
        "must_have_by_category": [{"category_id": "Serum", "ingredient_ids": ["ing-a"]}],
    }}))
    assert events[-1]["code"] == "INVALID_PREFERENCES"
    pipeline.product_service.client.search.assert_not_called()


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


def test_unknown_model_product_id_is_discarded_before_public_output(pipeline, request_payload, routine_state):
    routine_state["products_outputs"]["products_Sunscreen"].top_recommendations[0].product_id = "fabricated-id"
    events = asyncio.run(collect(request_payload))
    assert validate_events(events) == []
    assert "fabricated-id" not in json.dumps(events)
    assert any(event.get("node_id") == "compile" for event in events)


def test_explanation_provider_failure_keeps_the_approved_products(pipeline, request_payload, monkeypatch):
    monkeypatch.setattr(orchestration, "create_product_agent", lambda category: SimpleNamespace(
        invoke_async=AsyncMock(side_effect=RuntimeError("private provider error")),
    ))
    events = asyncio.run(collect(request_payload))
    assert validate_events(events) == []
    assert "private provider error" not in json.dumps(events)
    assert "/products/example.jpg" in json.dumps(events)


def test_explanation_timeout_cancels_the_call_and_completes_with_factual_text(pipeline, request_payload, monkeypatch):
    import agents.recommendation_nodes as nodes
    monkeypatch.setattr(nodes, "EXPLANATION_DEADLINE_SECONDS", 0.01)
    cancelled = []
    async def slow(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    monkeypatch.setattr(orchestration, "create_product_agent", lambda category: SimpleNamespace(invoke_async=slow))
    events = asyncio.run(collect(request_payload))
    assert cancelled == [True, True]
    assert validate_events(events) == []
    assert "/products/example.jpg" in json.dumps(events)


def test_explanation_guardrail_intervention_remains_terminal(pipeline, request_payload, monkeypatch):
    monkeypatch.setattr(orchestration, "create_product_agent", lambda category: SimpleNamespace(
        invoke_async=AsyncMock(return_value=SimpleNamespace(stop_reason="guardrail_intervened")),
    ))
    events = asyncio.run(collect(request_payload))
    assert events[-1]["type"] == "error" and events[-1]["code"] == "GUARDRAIL_BLOCKED"
    assert not any(event.get("node_id") == "compile" and "node_result" in event for event in events)


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
    pipeline.product_service.metadata.configuration.assert_not_called()


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


def test_unhealthy_catalog_stops_before_model_graphs(pipeline, request_payload):
    pipeline.product_service.metadata.readiness.side_effect = lambda *args: readiness(healthy=False, checked_at=time.time())
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
    orchestrator.product_service = SimpleNamespace(config=configuration())
    plan = StepAnalysisResult.model_validate(routine_state["step_analysis_data"])
    plan.routine_steps[0].step_name = "Not a catalog category"
    with pytest.raises(ValueError, match="(?i)(category|catalog|unknown|unsupported)"):
        orchestrator._build_prescribe_graph(plan.routine_steps)
