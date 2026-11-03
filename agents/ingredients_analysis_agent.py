"""Ingredients analysis agent factory for the graph pipeline.

Creates one Agent per skincare step. Each agent uses
get_available_ingredients_for_step to query DynamoDB and receives
step data + user profile as input text from graph dependency propagation.
"""

from strands import Agent

from config import get_ingredient_model, load_prompt

from .models import IngredientsAnalysisOutput
from .tools import get_available_ingredients_for_step, resolve_ingredient_names

def create_ingredients_agent(step_name: str) -> Agent:
    """Create an ingredients analysis agent for a specific skincare step.

    Each instance is unique (Graph validates no duplicate instances).

    Args:
        step_name: The skincare step name (e.g. "Cleanser", "Serum").

    Returns:
        Agent configured with the ingredients tool, named ingredients_{step_name}.
    """
    base_prompt = load_prompt("prompts/ingredients_analysis_prompt.txt")
    # Explicitly inject the step_name into the prompt for structured output
    system_prompt = f"{base_prompt}\n\nYOUR ASSIGNED STEP: {step_name}\nYou MUST use '{step_name}' as the step_name in your output."

    return Agent(
        model=get_ingredient_model(),
        system_prompt=system_prompt,
        tools=[get_available_ingredients_for_step, resolve_ingredient_names],
        callback_handler=None,
        name=f"ingredients_{step_name}",
        structured_output_model=IngredientsAnalysisOutput,
    )
