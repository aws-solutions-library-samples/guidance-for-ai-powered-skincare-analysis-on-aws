"""Configuration for skincare agents."""

import logging
import os
from pathlib import Path

from strands.models import BedrockModel
from agents.guarded_model import GuardedBedrockModel

logger = logging.getLogger(__name__)

# Supported models must also be allowed by terraform/iam.tf.
AVAILABLE_MODELS: dict[str, str] = {
    "claude-sonnet-5.5": "global.anthropic.claude-sonnet-5-5",
    "claude-haiku-5.5": "global.anthropic.claude-haiku-5-5",
}

DEFAULT_MODEL = "claude-sonnet-5.5"
FAST_MODEL = "claude-haiku-5.5"

# Model configuration
_selected_model = os.environ.get("MODEL_NAME", DEFAULT_MODEL)
if _selected_model not in AVAILABLE_MODELS:
    logger.warning(
        "Unknown MODEL_NAME '%s', falling back to '%s'. Available: %s",
        _selected_model,
        DEFAULT_MODEL,
        list(AVAILABLE_MODELS.keys()),
    )
    _selected_model = DEFAULT_MODEL

_aws_region = os.environ.get("AWS_REGION", "us-east-1")

MODEL_CONFIG = {
    "model_id": AVAILABLE_MODELS[_selected_model],
    "region_name": _aws_region,
    "streaming": True,
    "strict_tools": True,
    "max_tokens": 8192,
    "additional_request_fields": {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    },
}

FAST_MODEL_CONFIG = {
    "model_id": AVAILABLE_MODELS[FAST_MODEL],
    "region_name": _aws_region,
    "streaming": True,
    "strict_tools": True,
    "max_tokens": 8192,
    "additional_request_fields": {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "low"},
    },
}


def get_model() -> BedrockModel:
    """Get configured Bedrock model instance (primary, most capable)."""
    logger.info(
        "Using model: %s (%s)", _selected_model, AVAILABLE_MODELS[_selected_model]
    )
    return GuardedBedrockModel(**MODEL_CONFIG, **_guardrail_config())


def get_fast_model() -> BedrockModel:
    """Get fast Bedrock model instance (Haiku — for simple tasks)."""
    logger.info("Using fast model: %s (%s)", FAST_MODEL, AVAILABLE_MODELS[FAST_MODEL])
    return GuardedBedrockModel(**FAST_MODEL_CONFIG, **_guardrail_config())


def _guardrail_config() -> dict:
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    version = os.environ.get("GUARDRAIL_VERSION")
    if not guardrail_id and not version and os.environ.get("AGENTCORE_RUNTIME") != "true":
        return {}
    if not guardrail_id or not version:
        raise RuntimeError("Both GUARDRAIL_ID and GUARDRAIL_VERSION are required")
    return {
        "guardrail_id": guardrail_id,
        "guardrail_version": version,
        "guardrail_trace": "enabled",
        "guardrail_stream_processing_mode": "sync",
    }


def load_prompt(prompt_file: str, **context: str) -> str:
    """Load system prompt from file, substituting {{KEY}} placeholders.

    Placeholders use the format {{KEY}} and are replaced with values
    from the context kwargs. Unmatched placeholders are left as-is.

    Args:
        prompt_file: Path to the prompt file (relative or absolute).
        **context: Key-value pairs for placeholder substitution.
    """
    path = Path(prompt_file)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    content = path.read_text(encoding="utf-8").strip()

    for key, value in context.items():
        content = content.replace(f"{{{{{key}}}}}", value)

    return content
