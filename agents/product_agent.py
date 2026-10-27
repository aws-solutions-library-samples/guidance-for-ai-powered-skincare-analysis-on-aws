"""Explain server-selected products without search tools or catalog authority."""

from strands import Agent

from config import get_fast_model, load_prompt

from .models import ProductExplanations

def create_product_agent(step_name: str) -> Agent:
    """Create a product recommendation agent for a specific skincare step.

    Each instance is unique (Graph validates no duplicate instances).

    Args:
        step_name: The skincare step name (e.g. "Cleanser", "Serum").

    Returns:
        Agent configured with the products tool, named products_{step_name}.
    """
    base_prompt = load_prompt("prompts/product_agent_prompt.txt")
    # Explicitly inject the step_name into the prompt for structured output
    system_prompt = f"{base_prompt}\n\nYOUR ASSIGNED STEP: {step_name}\nYou MUST use '{step_name}' as the step_name in your output."

    return Agent(
        model=get_fast_model(),
        system_prompt=system_prompt,
        tools=[],
        callback_handler=None,
        name=f"products_{step_name}",
        structured_output_model=ProductExplanations,
    )
