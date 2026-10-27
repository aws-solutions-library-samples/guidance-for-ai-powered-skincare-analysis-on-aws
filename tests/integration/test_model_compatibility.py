"""Exercise native strict tools through the real pinned Strands adapter."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from botocore.exceptions import ClientError
from pydantic import BaseModel, ValidationError
import pytest
from strands import Agent
from strands.tools import convert_pydantic_to_tool_spec

import config
from agents.bedrock_schema import strict_tool_schema
from agents.errors import classify_error
from agents.guarded_model import GuardedBedrockModel
from agents.models import (
    IngredientsAnalysisOutput, ProductExplanations, SkinMetrics,
    SkinProfile, StepAnalysisResult,
)
from agents.tools import get_available_ingredients_for_step, resolve_ingredient_names


class Answer(BaseModel):
    answer: str


def text_response(text="Please provide structured output."):
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]


def tool_response(name, data):
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {
            "contentBlockIndex": 0,
            "start": {"toolUse": {"toolUseId": "test-call", "name": name}},
        }},
        {"contentBlockDelta": {
            "contentBlockIndex": 0, "delta": {"toolUse": {"input": json.dumps(data)}},
        }},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]


def model_with_responses(settings, responses):
    session = Mock(region_name="us-east-1")
    pending = iter(responses)

    def converse_stream(**request):
        # Reproduce the live service rejection that triggered the adapter fix.
        if request["modelId"].endswith("sonnet-5-5"):
            if request.get("toolConfig", {}).get("toolChoice") != {"auto": {}}:
                raise ClientError({"Error": {
                    "Code": "ValidationException", "Message": "Forced tools are unsupported",
                }}, "ConverseStream")
        return {"stream": iter(next(pending))}

    session.client.return_value.converse_stream.side_effect = converse_stream
    options = {key: deepcopy(value) for key, value in settings.items() if key != "region_name"}
    return GuardedBedrockModel(
        boto_session=session, **options,
        guardrail_id="test-guardrail", guardrail_version="1",
        guardrail_stream_processing_mode="sync",
    )


def collect(model, spec, **kwargs):
    async def run():
        return [event async for event in model.stream(
            [{"role": "user", "content": [{"text": "A synthetic contract test"}]}],
            [spec], **kwargs,
        )]
    return asyncio.run(run())


def walk_schema(schema):
    yield schema
    for key in ("properties", "$defs", "definitions"):
        for child in schema.get(key, {}).values():
            yield from walk_schema(child)
    if isinstance(schema.get("items"), dict):
        yield from walk_schema(schema["items"])
    for key in ("anyOf", "allOf", "oneOf"):
        for child in schema.get(key, []):
            yield from walk_schema(child)


SPECS = [
    convert_pydantic_to_tool_spec(schema)
    for schema in (SkinProfile, StepAnalysisResult, IngredientsAnalysisOutput, ProductExplanations)
] + [get_available_ingredients_for_step.tool_spec, resolve_ingredient_names.tool_spec]


@pytest.mark.parametrize("settings", [config.MODEL_CONFIG, config.FAST_MODEL_CONFIG])
@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec["name"])
def test_application_schemas_reach_converse_as_native_strict_tools(settings, spec):
    original = deepcopy(spec)
    model = model_with_responses(settings, [text_response()])
    collect(model, spec)
    request = model.client.converse_stream.call_args.kwargs
    assert request["modelId"] == settings["model_id"]
    assert request["inferenceConfig"] == {"maxTokens": 8192}
    assert request["additionalModelRequestFields"] == settings["additional_request_fields"]
    assert request["toolConfig"]["toolChoice"] == {"auto": {}}
    tool = request["toolConfig"]["tools"][0]["toolSpec"]
    assert tool["strict"] is True
    for node in walk_schema(tool["inputSchema"]["json"]):
        assert not {"minimum", "maximum", "minLength", "maxLength", "maxItems"} & node.keys()
        assert node.get("minItems", 0) <= 1
        if node.get("type") == "object" or "object" in node.get("type", []):
            assert node["additionalProperties"] is False
    assert request["guardrailConfig"]["streamProcessingMode"] == "sync"
    assert spec == original


def test_schema_property_names_and_original_constraints_are_preserved():
    schema = {
        "type": "object", "required": ["maximum"],
        "properties": {
            "maximum": {"type": "integer", "minimum": 0, "maximum": 100},
            "items": {"type": "array", "minItems": 2, "maxItems": 8, "items": {"type": "string"}},
        },
    }
    original = deepcopy(schema)
    result = strict_tool_schema(schema)
    assert result["required"] == ["maximum"]
    assert "minimum=0" in result["properties"]["maximum"]["description"]
    assert "maximum=100" in result["properties"]["maximum"]["description"]
    assert "minItems=2" in result["properties"]["items"]["description"]
    assert schema == original
    with pytest.raises(ValidationError):
        SkinMetrics(**dict.fromkeys(SkinMetrics.model_fields, 101))


def test_open_ended_schema_is_rejected_instead_of_silently_changing_its_meaning():
    with pytest.raises(ValueError, match="open-ended"):
        strict_tool_schema({"type": "object", "additionalProperties": {"type": "string"}})


def test_sonnet_structured_output_retry_uses_auto_and_still_validates():
    model = model_with_responses(config.MODEL_CONFIG, [
        text_response(), tool_response("Answer", {"answer": "ready"}),
    ])
    agent = Agent(model=model, structured_output_model=Answer, callback_handler=None)
    result = agent("Return ready")
    assert result.structured_output == Answer(answer="ready")
    requests = [call.kwargs for call in model.client.converse_stream.call_args_list]
    assert len(requests) == 2
    assert requests[1]["toolConfig"]["toolChoice"] == {"auto": {}}
    assert len(requests[1]["toolConfig"]["tools"]) == 1
    assert requests[1]["toolConfig"]["tools"][0]["toolSpec"]["strict"] is True
    assert requests[1]["additionalModelRequestFields"]["thinking"] == {"type": "adaptive"}


def test_missing_structured_output_fails_after_bounded_retry():
    model = model_with_responses(config.MODEL_CONFIG, [text_response(), text_response()])
    agent = Agent(model=model, structured_output_model=Answer, callback_handler=None)
    with pytest.raises(Exception, match="failed to invoke the structured output"):
        agent("Return ready")
    assert model.client.converse_stream.call_count == 2


def test_native_schema_retry_does_not_bypass_guardrails():
    model = model_with_responses(config.MODEL_CONFIG, [
        text_response(),
        [{"messageStart": {"role": "assistant"}},
         {"messageStop": {"stopReason": "guardrail_intervened"}}],
    ])
    agent = Agent(model=model, structured_output_model=Answer, callback_handler=None)
    with pytest.raises(Exception) as failure:
        agent("Return ready")
    assert classify_error(failure.value).code == "GUARDRAIL_BLOCKED"
    assert model.client.converse_stream.call_count == 2


def test_forced_choice_among_multiple_tools_is_not_silently_weakened():
    model = model_with_responses(config.MODEL_CONFIG, [])

    async def run():
        return [event async for event in model.stream(
            [{"role": "user", "content": [{"text": "test"}]}],
            SPECS[:2], tool_choice={"any": {}},
        )]
    with pytest.raises(ValueError, match="exactly one tool"):
        asyncio.run(run())
    model.client.converse_stream.assert_not_called()


def test_supported_profiles_are_all_in_the_runtime_iam_policy():
    policy = (Path(__file__).parents[2] / "terraform" / "iam.tf").read_text()
    assert set(config.AVAILABLE_MODELS.values()) == {
        "global.anthropic.claude-sonnet-5-5", "global.anthropic.claude-haiku-5-5",
    }
    for profile in config.AVAILABLE_MODELS.values():
        assert f"inference-profile/{profile}" in policy
        assert f"foundation-model/{profile.removeprefix('global.')}" in policy


def test_configuration_import_does_not_depend_on_package_import_order():
    result = subprocess.run(
        [sys.executable, "-c", "import config; from agents import Orchestrator; "
         "assert callable(config.get_model) and callable(Orchestrator)"],
        cwd=Path(__file__).parents[2], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
