"""Skin analysis agent factory for the graph pipeline.

Creates a Strands Agent that accepts multi-modal ContentBlock input
(images + text) and returns SkinProfile JSON via structured_output_model.
"""

from strands import Agent

from config import get_model, load_prompt

from .models import SkinProfile

def create_skin_analysis_agent() -> Agent:
    """Create a skin analysis agent for use as a graph node.

    Returns:
        Agent configured with SkinProfile structured output, no tools.
    """
    return Agent(
        model=get_model(),
        system_prompt=load_prompt("prompts/skin_analysis_prompt.txt"),
        tools=[],
        callback_handler=None,
        name="skin_analysis",
        structured_output_model=SkinProfile,
    )
