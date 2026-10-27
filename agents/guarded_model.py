"""Bedrock strict-tool compatibility and typed guardrail interventions."""

from strands.models import BedrockModel

from .bedrock_schema import strict_tool_schema
from .errors import AnalysisFailure, guardrail_failure


class GuardedBedrockModel(BedrockModel):
    async def stream(
        self, messages, tool_specs=None, system_prompt=None, *,
        tool_choice=None, system_prompt_content=None, **kwargs,
    ):
        if tool_specs and self.config.get("strict_tools"):
            tool_specs = [
                {**spec, "inputSchema": {"json": strict_tool_schema(spec["inputSchema"]["json"])}}
                for spec in tool_specs
            ]
        # Strands 1.43 retries missing structured output with a single forced
        # tool. Sonnet 5.5 only supports auto. Keep the SDK's bounded retry and
        # Pydantic validation; never substitute unvalidated text as success.
        if (
            self.config["model_id"].endswith("anthropic.claude-sonnet-5-5")
            and tool_choice
            and ("any" in tool_choice or "tool" in tool_choice)
        ):
            if not tool_specs or len(tool_specs) != 1:
                raise ValueError("Sonnet 5.5 structured-output retry requires exactly one tool")
            name = tool_specs[0]["name"]
            if "tool" in tool_choice and tool_choice["tool"]["name"] != name:
                raise ValueError("Requested structured-output tool does not match the schema")
            tool_choice = {"auto": {}}
            system_prompt_content = list(
                system_prompt_content
                or ([{"text": system_prompt}] if system_prompt else [])
            )
            system_prompt_content.append({
                "text": f"Return the requested result by calling the {name} tool."
            })
        blocked = None
        async for event in super().stream(
            messages, tool_specs, system_prompt, tool_choice=tool_choice,
            system_prompt_content=system_prompt_content, **kwargs,
        ):
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
