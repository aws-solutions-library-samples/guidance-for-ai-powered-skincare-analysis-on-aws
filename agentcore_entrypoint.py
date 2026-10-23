"""AgentCore Runtime entrypoint for skincare analysis.

Async generator entrypoint: receives request, runs the Graph orchestrator,
and yields serialized Strands streaming events. AgentCore handles SSE transport.
The client receives results directly; job_id is used only for log correlation.
"""

import logging
from typing import Any
from uuid import uuid4

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.multiagent.base import Status

from agents.orchestrator import Orchestrator
from agents.errors import AnalysisFailure, error_event
from agents.input_validation import ImageLimitError, decode_images, validate_payload

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = BedrockAgentCoreApp()

def _decode_images(job_id: str, images: list[str]) -> list[bytes]:
    """Compatibility wrapper for local callers; all inputs use the same limits."""
    return decode_images(images)


def _serialize_event(event: dict, request_id: str = "") -> dict:
    """Serialize a Strands graph event into a JSON-safe dict.

    NodeResult and AgentResult are dataclasses containing Pydantic models
    and enums that json.dumps cannot handle. We explicitly serialize them
    using their .to_dict() methods and extract structured_output via
    Pydantic's .model_dump().
    """
    event_type = event.get("type")
    if event_type == "error":
        return error_event(AnalysisFailure("ANALYSIS_FAILED"), request_id)

    if event_type == "multiagent_node_start":
        return {
            "type": "multiagent_node_start",
            "node_id": event["node_id"],
        }

    if event_type == "multiagent_node_stop":
        node_result = event.get("node_result")
        serialized: dict[str, Any] = {
            "type": "multiagent_node_stop",
            "node_id": event["node_id"],
        }
        if node_result:
            result_dict = node_result.to_dict()
            # Inject structured_output (not included by default in to_dict())
            try:
                so = node_result.result.structured_output
                if so is not None:
                    result_dict["result"]["structured_output"] = so.model_dump()
            except (AttributeError, TypeError):
                pass
            serialized["node_result"] = result_dict
        return serialized

    if event_type == "multiagent_result":
        graph_result = event.get("result")
        serialized_result = None
        if graph_result:
            try:
                serialized_result = graph_result.to_dict()
            except (AttributeError, TypeError):
                serialized_result = str(graph_result)
        return {
            "type": "multiagent_result",
            "result": serialized_result,
        }

    # For other event types (multiagent_node_stream, etc.) pass through
    # only JSON-safe keys
    safe = {"type": event_type}
    if "node_id" in event:
        safe["node_id"] = event["node_id"]
    # Raw model deltas, guardrail traces and tool errors are not public API data.
    return safe


@app.entrypoint
async def invoke(payload: dict, context: object):
    """Async generator entrypoint that yields serialized Strands streaming events.

    AgentCore wraps each yielded dict in an SSE frame (data: {...}\\n\\n).
    The frontend interprets multiagent_node_start, multiagent_node_stop,
    and multiagent_result events to drive the UI.
    """
    job_id = str(uuid4())
    try:
        try:
            # Keep a valid correlation ID even when image validation fails.
            if isinstance(payload, dict):
                candidate = payload.get("job_id")
                if isinstance(candidate, str) and 1 <= len(candidate) <= 128 and all(
                    char.isascii() and (char.isalnum() or char in "_-") for char in candidate
                ):
                    job_id = candidate
            job_id, image_bytes_list = validate_payload(payload)
        except ImageLimitError as exc:
            raise AnalysisFailure("REQUEST_TOO_LARGE") from exc
        except (ValueError, TypeError) as exc:
            raise AnalysisFailure("INVALID_INPUT") from exc
        compiled = False
        node_failure = None

        orchestrator = Orchestrator()
        async for event in orchestrator.run(image_bytes_list):
            if event.get("type") == "error":
                raise AnalysisFailure("ANALYSIS_FAILED")
            if event.get("type") == "multiagent_node_stop":
                node_result = event.get("node_result")
                if node_result is not None and node_result.status != Status.COMPLETED:
                    node_failure = node_result.result if isinstance(node_result.result, Exception) else AnalysisFailure("ANALYSIS_FAILED")
                    # Graph next raises this exception. Do not send its raw NodeResult
                    # first: that would obscure the typed error (and leak details).
                    continue
                if getattr(getattr(node_result, "result", None), "stop_reason", None) == "guardrail_intervened":
                    raise AnalysisFailure("GUARDRAIL_BLOCKED")
            if node_failure:
                continue
            if event.get("type") == "multiagent_result" and event["result"].status != Status.COMPLETED:
                raise AnalysisFailure("ANALYSIS_FAILED")
            if (
                event.get("type") == "multiagent_node_stop"
                and event.get("node_id") == "compile"
            ):
                node_result = event.get("node_result")
                compiled = node_result is not None and node_result.status == Status.COMPLETED

            yield _serialize_event(event, job_id)

        if node_failure:
            raise node_failure
        if not compiled:
            raise AnalysisFailure("INVALID_RESPONSE")
        logger.info("Job %s: COMPLETED successfully", job_id)

    except Exception as exc:
        logger.error("Job %s: FAILED - %s", job_id, exc, exc_info=True)
        public_error = error_event(exc, job_id)
        logger.info("Job %s: error_code=%s", job_id, public_error["code"])
        yield public_error


if __name__ == "__main__":
    app.run()
