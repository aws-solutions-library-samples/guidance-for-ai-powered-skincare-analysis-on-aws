"""Opt-in explanation evaluation with fictional profiles and product records.

Uses the real product node, factory, model and selected deployment's guardrail.
No photos, catalog writes or extra deployed resources. Local source is exercised;
deployment identity and a manual browser check must be verified separately.
"""

import argparse
import asyncio
from datetime import datetime, timezone
from functools import partial
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace
from unittest.mock import patch

import boto3
from botocore.config import Config

import config
from agents.catalog_binding import render_products
from agents.guarded_model import GuardedBedrockModel
from agents.models import IngredientsAnalysisOutput, StepAnalysisResult
from agents.product_agent import create_product_agent
from agents.recommendation_nodes import ProductSelectionNode
from agents.search.contracts import Preferences, SearchResult, SearchTrace, SelectedProduct
from tests.live_release import require, validate_target
from tests.search_fixtures import product, request


def cases():
    """The first two cases keep the products identical and change the profile."""
    for name, category, skin_type, concerns, goal, when, identities in [
        ("dry_cleanser", "Cleanser", "Dry", ["tightness after cleansing"],
         "Maintain comfort during gentle cleansing", "Morning & Evening", ("glycerin", "panthenol")),
        ("oily_cleanser", "Cleanser", "Oily", ["excess shine"],
         "Cleanse without over-stripping skin", "Morning & Evening", ("glycerin", "panthenol")),
        ("evening_moisturiser", "Moisturiser", "Dry", ["dry patches"],
         "Maintain hydration and comfort overnight", "Evening", ("glycerin", "squalane")),
        ("sensitive_serum", "Serum", "Sensitive", ["discomfort after cleansing"],
         "Keep the morning routine gentle and comfortable", "Morning", ("panthenol", "niacinamide")),
    ]:
        functions = {
            "glycerin": ("Glycerin", "Humectant that helps retain moisture"),
            "panthenol": ("Panthenol", "Helps maintain a comfortable, hydrated skin feel"),
            "squalane": ("Squalane", "Emollient that softens dry-feeling skin"),
            "niacinamide": ("Niacinamide", "Supports skin barrier function"),
        }
        steps = ["Cleanser", "Serum", "Moisturiser", "Sunscreen"]
        plan = StepAnalysisResult(
            user_profile={"skin_type": skin_type, "age": "25-32", "concerns": concerns,
                          "routine_rationale": goal},
            routine_steps=[{
                "step_name": step, "justification": goal if step == category else "Basic cosmetic care",
                "why_this_step_for_you": goal if step == category else "Keep the routine simple",
                "when": when if step == category else (
                    "Morning" if step == "Sunscreen" else "Morning & Evening"
                ),
            } for step in steps],
            routine_summary={"total_steps": len(steps), "benefits": [goal],
                             "usage_notes": ["Respect each product's label directions"]},
        )
        ingredients = IngredientsAnalysisOutput(
            step_name=category, key_ingredients=[{
                "ingredient_id": identifier, "name": functions[identifier][0],
                "benefit": functions[identifier][1],
                "why_for_you": f"{functions[identifier][1]}; relevant to {concerns[0]} and the goal: {goal}.",
                "usage": "Ingredient background only: no product concentration or dose is supplied.",
            } for identifier in identities] + [{
                "ingredient_id": "retinol", "name": "Retinol", "benefit": "UNMATCHED fixture",
                "why_for_you": "UNMATCHED fixture; never attribute this to the selected products",
                "usage": "UNMATCHED fixture",
            }],
            analysis_notes="Combination-level text mentions unmatched retinol and must not be forwarded.",
        )
        # Product 1 has both ingredients; product 2 has only the first.
        selected = tuple(SelectedProduct(
            product=product(
                f"example-{category.lower()}-{index}", category_id=category,
                name=f"Example {category} {index}", ingredient_ids=list(matched),
                raw_ingredients=[functions[key][0] for key in matched],
            ),
            matched_ingredient_ids=matched, matched_must_have_ingredient_ids=(), preferred_count=3,
        ) for index, matched in enumerate((identities, identities[:1]), start=1))
        result = SearchResult(
            request=request(category_id=category, preferred_ingredient_ids=(*identities, "retinol")),
            products=selected, status="matched",
            trace=SearchTrace(retrieved=2, hydrated=2, hydration_batches=1, dependency_retries=0,
                              dropped_missing=0, dropped_ineligible=0, dropped_changed=0, elapsed_ms=1),
        )
        yield name, result, ingredients, plan


def previous_input(result, ingredients, plan, *, currency_minor_units=None):
    """Reproduce the former input assembly only when a baseline is requested."""
    return {
        "user_profile": plan.user_profile.model_dump(),
        "approved_products": render_products(
            result, {item.ingredient_id: item.name for item in ingredients.key_ingredients},
            currency_minor_units=currency_minor_units,
        ).model_dump(),
    }


def content_checks(explanation, result, ingredients, plan):
    """Mechanical gates supplement, but cannot replace, reviewing the wording."""
    if explanation is None:
        return {"agent_explanation_present": False}
    all_text = " ".join(
        item.why_for_you + " " + item.usage_tip for item in explanation.products
    ).lower()
    names = {item.ingredient_id: item.name.lower() for item in ingredients.key_ingredients}
    checks = {
        "agent_explanation_present": True,
        "product_binding": [item.product_id for item in explanation.products]
        == [item.product.product_id for item in result.products],
        "nonblank": all(item.why_for_you.strip() and item.usage_tip.strip()
                        for item in explanation.products),
        "no_unmatched_ingredient_names": all(
            not any(
                name in (text.why_for_you + " " + text.usage_tip).lower()
                for identifier, name in names.items()
                if identifier not in selected.matched_ingredient_ids
            )
            for text, selected in zip(explanation.products, result.products, strict=True)
        ),
        "no_numeric_dose_claim": re.search(
            r"\b\d+(?:\.\d+)?\s*(?:%|drops?\b|pumps?\b|minutes?\b|times?\b)", all_text,
        ) is None,
        "no_generic_tip_only": all(
            item.usage_tip.strip().lower().rstrip(".") != "follow the product label"
            for item in explanation.products
        ),
    }
    when = next(step.when for step in plan.routine_steps if step.step_name == result.request.category_id)
    checks["required_time_mentioned"] = all(
        ("morning" in item.usage_tip.lower() or when == "Evening")
        and ("evening" in item.usage_tip.lower() or when == "Morning")
        for item in explanation.products
    )
    return checks


async def evaluate(case, model_factory, baseline=None):
    name, result, ingredients, plan = case
    state = {
        "request_id": result.request.request_id, "preferences": Preferences(),
        "step_analysis_data": plan, "ingredients_outputs": {f"ingredients_{ingredients.step_name}": ingredients},
        "search_results": {}, "product_explanations": {}, "explanation_hashes": {}, "products_outputs": {},
        "product_service": SimpleNamespace(
            search=lambda *args, **kwargs: result,
            config=SimpleNamespace(currency_minor_units={"GBP": 2}),
        ),
    }
    with patch("agents.product_agent.get_explanation_model", side_effect=model_factory):
        if baseline is None:
            agent = create_product_agent(result.request.category_id)
        else:
            with patch("agents.product_agent.load_prompt", return_value=baseline):
                agent = create_product_agent(result.request.category_id)

    usage = {}
    returned = {}

    async def record(*args, **kwargs):
        response = await agent.invoke_async(*args, **kwargs)
        usage.update(response.metrics.accumulated_usage)
        returned["structured_output"] = (
            response.structured_output.model_dump(mode="json")
            if hasattr(response.structured_output, "model_dump") else response.structured_output
        )
        return response

    node = ProductSelectionNode(result.request.category_id, SimpleNamespace(invoke_async=record))
    start = time.monotonic()
    if baseline is None:
        await node.invoke_async("synthetic evaluation", invocation_state=state)
    else:
        with patch("agents.recommendation_nodes.explanation_input", side_effect=previous_input):
            await node.invoke_async("synthetic evaluation", invocation_state=state)
    explanation = state["product_explanations"][node.id]
    return {
        "case": name, "seconds": round(time.monotonic() - start, 3), "usage": usage,
        "checks": content_checks(explanation, result, ingredients, plan),
        "output": state["products_outputs"][node.id].model_dump(mode="json"),
        "model_returned": returned,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-model-invocations", action="store_true")
    parser.add_argument("--baseline-prompt", type=Path)
    parser.add_argument("--repetitions", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--native-strict", action="store_true",
                        help="Diagnostic comparison: enable native strict decoding for explanation output")
    args = parser.parse_args()
    if not args.allow_model_invocations:
        parser.error("--allow-model-invocations is required")
    outputs = {key: value["value"] for key, value in json.loads(args.outputs.read_text()).items()}
    session = boto3.Session(region_name=outputs["aws_region"])
    validate_target(outputs, args.expected_account, session.client("sts").get_caller_identity()["Account"])
    runtime = session.client("bedrock-agentcore-control").get_agent_runtime(
        agentRuntimeId=outputs["agentcore_runtime_id"],
    )
    require(runtime["agentRuntimeArn"] == outputs["agentcore_runtime_arn"], "Runtime mismatch")
    settings = runtime["environmentVariables"]
    model_settings = {key: value for key, value in config.EXPLANATION_MODEL_CONFIG.items() if key != "region_name"}
    if args.native_strict:
        model_settings["strict_tools"] = True
    model_factory = partial(
        GuardedBedrockModel, boto_session=session,
        **model_settings,
        guardrail_id=settings["GUARDRAIL_ID"], guardrail_version=settings["GUARDRAIL_VERSION"],
        guardrail_stream_processing_mode="sync",
        boto_client_config=Config(read_timeout=30, retries={"total_max_attempts": 1}),
    )
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(), "account": args.expected_account,
        "model": model_settings, "runs": [], "human_quality_review": "PENDING",
        "scope": "Local production node/factory against live Bedrock; synthetic data and stubbed product search",
    }
    variants = [("candidate", None)]
    if args.baseline_prompt:
        variants.insert(0, ("baseline", args.baseline_prompt.read_text()))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for repetition in range(args.repetitions):
        for variant, baseline in variants:
            for case in cases():
                try:
                    row = asyncio.run(evaluate(case, model_factory, baseline))
                    row["mechanical_status"] = "PASS" if all(row["checks"].values()) else "FAIL"
                except Exception as exc:
                    row = {"case": case[0], "mechanical_status": "FAIL", "error_type": type(exc).__name__}
                row.update(variant=variant, repetition=repetition + 1)
                report["runs"].append(row)
                args.report.write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps({key: value for key, value in row.items() if key != "output"}), flush=True)
    raise SystemExit(any(row["mechanical_status"] != "PASS" for row in report["runs"]
                         if row["variant"] == "candidate"))


if __name__ == "__main__":
    main()
