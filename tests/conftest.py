"""Shared fixtures. The default suites never contact AWS or the network."""

import socket
import base64
import io
from unittest.mock import Mock

import pytest
from PIL import Image

from agents.models import IngredientsAnalysisOutput, ProductAnalysisOutput, StepAnalysisResult
from agents.search.contracts import Preferences, SearchResult, SearchTrace, SelectedProduct
from tests.search_fixtures import configuration, product, request


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
    state = {
        "request_id": "request-1", "preferences": Preferences(), "api_version": 2,
        "product_service": Mock(),
        "step_analysis_data": plan.model_dump(),
        "ingredients_outputs": {
            f"ingredients_{step.step_name}": IngredientsAnalysisOutput(
                step_name=step.step_name,
                key_ingredients=[{
                    "ingredient_id": "ing-a", "name": "Glycerin", "benefit": "Hydration",
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
    state["search_results"] = {
        f"products_{step.step_name}": SearchResult(
            request=request(
                step_id=f"step-{step.step_name}", category_id=step.step_name,
                preferred_ingredient_ids=("ing-a",),
            ), status="matched",
            products=(SelectedProduct(
                product=product(
                    f"id-{step.step_name}", name=f"Example {step.step_name}",
                    category_id=step.step_name, ingredient_ids=["ing-a"],
                    image_path="/products/example.jpg", price_minor=1200,
                ),
                matched_ingredient_ids=("ing-a",), matched_must_have_ingredient_ids=(),
                preferred_count=1,
            ),),
            trace=SearchTrace(
                retrieved=1, hydrated=1, hydration_batches=1, dependency_retries=0,
                dropped_missing=0, dropped_ineligible=0, dropped_changed=0, elapsed_ms=1,
            ),
        ) for step in plan.routine_steps
    }
    state["product_service"].finalize.side_effect = lambda results: results
    state["product_service"].config = configuration()
    return state
