"""Step analysis agent factory for the graph pipeline.

Creates a Strands Agent that receives skin profile text from the
skin_analysis node via graph dependency propagation and returns
StepAnalysisResult JSON via structured_output_model.
"""

from strands import Agent

from catalog import load_catalog
from config import get_fast_model, load_prompt

from .models import StepAnalysisResult

def create_step_analysis_agent() -> Agent:
    """Create a step analysis agent for use as a graph node.

    Returns:
        Agent configured with StepAnalysisResult structured output, no tools.
    """
    catalog = load_catalog()
    categories_block = "\n".join(f"- {cat}" for cat in catalog.categories)

    return Agent(
        model=get_fast_model(),
        system_prompt=load_prompt(
            "prompts/step_analysis_prompt.txt",
            CATEGORIES=categories_block,
        ),
        tools=[],
        callback_handler=None,
        name="step_analysis",
        structured_output_model=StepAnalysisResult,
    )
