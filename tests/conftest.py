"""Shared fixtures. The default suites never contact AWS or the network."""

import socket
import base64
import io

import pytest
from PIL import Image

from agents.models import IngredientsAnalysisOutput, ProductAnalysisOutput, StepAnalysisResult


@pytest.fixture
def valid_image():
    output = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(output, format="JPEG")
    return base64.b64encode(output.getvalue()).decode()


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def reject_connection(*args, **kwargs):
        raise AssertionError("Network access is forbidden in offline tests")

    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


@pytest.fixture
def routine_state():
    plan = StepAnalysisResult.model_validate({
        "user_profile": {
            "skin_type": "Dry", "age": "25-32", "concerns": ["dryness"],
            "routine_rationale": "Cleanse gently and protect from sunlight.",
        },
        "routine_steps": [
            {
                "step_name": name, "justification": f"Use {name}",
                "why_this_step_for_you": "Suitable for dry skin", "when": "Morning",
            }
            for name in ("Cleanser", "Sunscreen")
        ],
        "routine_summary": {
            "total_steps": 2, "benefits": ["Hydration"], "usage_notes": ["Use daily"],
        },
    })
    return {
        "step_analysis_data": plan.model_dump(),
        "ingredients_outputs": {
            f"ingredients_{step.step_name}": IngredientsAnalysisOutput(
                step_name=step.step_name,
                key_ingredients=[{
                    "name": "Glycerin", "benefit": "Hydration",
                    "why_for_you": "Helps dry skin", "usage": "Daily",
                }],
                analysis_notes="A gentle choice",
            )
            for step in plan.routine_steps
        },
        "products_outputs": {
            f"products_{step.step_name}": ProductAnalysisOutput(
                step_name=step.step_name,
                top_recommendations=[{
                    "product_id": f"id-{step.step_name}",
                    "name": f"Example {step.step_name}", "price": "£12.00",
                    "match_score": "100%", "matched_ingredients": ["Glycerin"],
                    "why_for_you": "Hydration", "usage_tip": "Use as directed",
                    "image_url": "/products/example.jpg",
                }],
            )
            for step in plan.routine_steps
        },
        "trusted_products": {
            f"products_{step.step_name}": {
                f"id-{step.step_name}": {
                    "product_id": f"id-{step.step_name}", "product_name": f"Example {step.step_name}",
                    "price": "£12.00", "match_score": "100%", "matched_ingredients": ["Glycerin"],
                    "image_url": "/products/example.jpg",
                },
            }
            for step in plan.routine_steps
        },
    }
