"""Translate Bedrock interventions before Strands validates structured output."""

from strands.models import BedrockModel

from .errors import AnalysisFailure, guardrail_failure


class GuardedBedrockModel(BedrockModel):
    async def stream(self, *args, **kwargs):
        blocked = None
        async for event in super().stream(*args, **kwargs):
            if event.get("messageStop", {}).get("stopReason") == "guardrail_intervened":
                blocked = blocked or AnalysisFailure("GUARDRAIL_BLOCKED")
            if "redactContent" in event:
                blocked = blocked or AnalysisFailure("GUARDRAIL_BLOCKED")
            trace = event.get("metadata", {}).get("trace", {}).get("guardrail", {})
            blocked = guardrail_failure(trace) or blocked
            # Drain the stream for its final assessment and to finish the SDK worker.
            # Never let a blocked stop reach structured-output parsing as a ValueError.
            if blocked is None:
                yield event
        if blocked is not None:
            raise blocked
