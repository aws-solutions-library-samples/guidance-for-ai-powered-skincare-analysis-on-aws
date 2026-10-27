"""Real pinned Bedrock/Strands/Graph/AgentCore adapters, with only AWS mocked."""

from unittest.mock import Mock
import asyncio

import pytest
from botocore.exceptions import ClientError
from pydantic import BaseModel
from strands import Agent
from strands.multiagent import GraphBuilder
from strands.types.exceptions import EventLoopException

import agentcore_entrypoint as entrypoint
import config
from agents.errors import AnalysisFailure, classify_error
from agents.guarded_model import GuardedBedrockModel
from tests.live_sse import read_events


class Output(BaseModel):
    answer: str


def bedrock_model(stream):
    session = Mock(region_name="us-east-1")
    session.client.return_value.converse_stream.return_value = {"stream": iter(stream)}
    return GuardedBedrockModel(
        boto_session=session, model_id="test-model",
        guardrail_id="test-guardrail", guardrail_version="2",
        guardrail_stream_processing_mode="sync",
    )


@pytest.mark.parametrize("policy,code", [
    ({"contentPolicy": {"filters": [{"type": "PROMPT_ATTACK", "action": "BLOCKED"}]}}, "GUARDRAIL_PROMPT_ATTACK"),
    ({"contentPolicy": {"filters": [{"type": "VIOLENCE", "action": "BLOCKED"}]}}, "GUARDRAIL_CONTENT"),
    ({"sensitiveInformationPolicy": {"piiEntities": [{"type": "EMAIL", "action": "BLOCKED", "match": "private@example.invalid"}]}}, "GUARDRAIL_SENSITIVE_DATA"),
    ({"topicPolicy": {"topics": [{"name": "medical-diagnosis", "action": "BLOCKED"}]}}, "GUARDRAIL_TOPIC"),
    ({}, "GUARDRAIL_BLOCKED"),
])
@pytest.mark.parametrize("direction", ["inputAssessment", "outputAssessments"])
def test_blocked_model_reaches_http_sse_as_one_typed_error(monkeypatch, policy, code, direction, valid_image):
    from starlette.testclient import TestClient

    model = bedrock_model([
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Private provider block message"}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "guardrail_intervened"}},
        {"metadata": {"trace": {"guardrail": {direction: {"test-guardrail": [policy] if direction == "outputAssessments" else policy}}}}},
    ])
    builder = GraphBuilder()
    builder.add_node(Agent(model=model, structured_output_model=Output, callback_handler=None), "skin_analysis")
    builder.set_entry_point("skin_analysis")
    graph = builder.build()

    class Pipeline:
        async def run(self, images):
            async for event in graph.stream_async("Analyze skincare"):
                yield event

    monkeypatch.setattr(entrypoint, "Orchestrator", Pipeline)
    with TestClient(entrypoint.app) as client:
        response = client.post("/invocations", json={"job_id": "test-reference", "images": [valid_image]})
    assert response.status_code == 200
    events = read_events(response)
    failures = [event for event in events if event["type"] == "error"]
    assert len(failures) == 1
    assert failures[0]["code"] == code
    assert failures[0]["request_id"] == "test-reference"
    assert failures[0]["retryable"] is False
    assert not any(event["type"] in {"multiagent_node_stop", "multiagent_result"} for event in events)
    assert "private@example.invalid" not in response.text
    assert "Private provider block message" not in response.text
    sent = model.client.converse_stream.call_args.kwargs
    assert sent["guardrailConfig"]["guardrailVersion"] == "2"
    assert sent["guardrailConfig"]["streamProcessingMode"] == "sync"


@pytest.mark.parametrize("provider_code,public_code", [
    ("ThrottlingException", "RATE_LIMITED"),
    ("ModelTimeoutException", "TIMEOUT"),
    ("AccessDeniedException", "SERVICE_UNAVAILABLE"),
    ("InternalServerException", "SERVICE_UNAVAILABLE"),
])
def test_sdk_wrapped_provider_errors_keep_their_category(provider_code, public_code):
    wrapped = EventLoopException(ClientError(
        {"Error": {"Code": provider_code, "Message": "private account details"}}, "ConverseStream",
    ))
    assert classify_error(wrapped).code == public_code
    assert "private" not in str(classify_error(wrapped))


@pytest.mark.parametrize("factory", [config.get_model, config.get_fast_model])
def test_both_model_factories_wire_guardrail_and_fail_on_partial_config(monkeypatch, factory):
    constructor = Mock()
    monkeypatch.setattr(config, "GuardedBedrockModel", constructor)
    monkeypatch.setenv("GUARDRAIL_ID", "configured-id")
    monkeypatch.setenv("GUARDRAIL_VERSION", "2")
    factory()
    assert constructor.call_args.kwargs["guardrail_id"] == "configured-id"
    assert constructor.call_args.kwargs["guardrail_version"] == "2"
    monkeypatch.delenv("GUARDRAIL_VERSION")
    with pytest.raises(RuntimeError, match="Both GUARDRAIL"):
        factory()


def test_unknown_failure_is_not_mislabeled_as_a_guardrail():
    assert classify_error(RuntimeError("guardrail unavailable")).code == "ANALYSIS_FAILED"
    assert classify_error(AnalysisFailure("GUARDRAIL_BLOCKED")).code == "GUARDRAIL_BLOCKED"


def test_allowed_model_stream_passes_through_unchanged():
    stream = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Use moisturizer."}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"trace": {"guardrail": {"inputAssessment": {
            "test-guardrail": {"contentPolicy": {"filters": [{"type": "PROMPT_ATTACK", "action": "NONE"}]}}
        }}}}},
    ]
    model = bedrock_model(stream)

    async def collect():
        return [event async for event in model.stream([{"role": "user", "content": [{"text": "Skincare please"}]}])]

    assert asyncio.run(collect()) == stream
