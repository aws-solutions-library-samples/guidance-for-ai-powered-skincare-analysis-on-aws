"""Opt-in Bedrock contracts using synthetic data, not personal photos.

Runs local application model code against Bedrock and reads the test catalog.
Does not prove that the deployed runtime contains this local revision.
"""

import argparse
import asyncio
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

import boto3
from botocore.config import Config
from PIL import Image
from pydantic import BaseModel
from strands import Agent

import config
from agents.guarded_model import GuardedBedrockModel
from agents.ingredients_analysis_agent import create_ingredients_agent
from agents.models import (
    IngredientsAnalysisOutput, ProductExplanations, SkinProfile, StepAnalysisResult,
)
from agents.search.catalog import CatalogMetadata
from agents.search.clients import DynamoReads
from agents.product_repository import ProductService
from agents.search.contracts import Preferences
from agents.tools import get_available_ingredients_for_step, resolve_ingredient_names
from tests.live_release import require, validate_target


class ContractAnswer(BaseModel):
    answer: str


def fixtures():
    profile = {
        "skin_type": "Normal", "age": "25-32", "concerns": ["dryness"],
        "current_condition": "Mild dryness", "recommended_goals": "Maintain hydration",
        "skin_metrics": dict.fromkeys(
            ["skin_health", "hydration", "texture", "pore_size", "elasticity", "radiance"], 70,
        ),
        "strengths": ["Even appearance"],
    }
    plan = {
        "user_profile": {
            "skin_type": "Normal", "age": "25-32", "concerns": ["dryness"],
            "routine_rationale": "A simple cosmetic routine",
        },
        "routine_steps": [{
            "step_name": name, "justification": "Basic care",
            "why_this_step_for_you": "Maintain comfort", "when": "Morning",
        } for name in ["Cleanser", "Moisturizer"]],
        "routine_summary": {
            "total_steps": 2, "benefits": ["Comfort"], "usage_notes": ["Follow the label"],
        },
    }
    ingredients = {
        "step_name": "Cleanser", "key_ingredients": [{
            "ingredient_id": "synthetic-contract-glycerin", "name": "Glycerin",
            "benefit": "Hydration", "why_for_you": "Comfort",
            "usage": "Follow the label",
        }], "analysis_notes": "Synthetic contract fixture",
    }
    products = {
        "step_name": "Cleanser", "products": [{
            "product_id": "synthetic-contract-only", "why_for_you": "Comfort",
            "usage_tip": "Follow the label",
        }],
    }
    return [
        (SkinProfile, profile, config.MODEL_CONFIG),
        (StepAnalysisResult, plan, config.FAST_MODEL_CONFIG),
        (IngredientsAnalysisOutput, ingredients, config.INGREDIENT_MODEL_CONFIG),
        (ProductExplanations, products, config.EXPLANATION_MODEL_CONFIG),
    ]


def run(args, report):
    outputs = {key: entry["value"] for key, entry in json.loads(args.outputs.read_text()).items()}
    boto3.setup_default_session(region_name=outputs["aws_region"])
    session = boto3.Session(region_name=outputs["aws_region"])
    caller = session.client("sts").get_caller_identity()
    validate_target(outputs, args.expected_account, caller["Account"])
    runtime = session.client("bedrock-agentcore-control").get_agent_runtime(
        agentRuntimeId=outputs["agentcore_runtime_id"],
    )
    require(runtime["agentRuntimeArn"] == outputs["agentcore_runtime_arn"],
            "Runtime differs from the selected deployment")
    runtime_settings = runtime["environmentVariables"]
    require(runtime_settings["PRODUCTS_TABLE_NAME"] == outputs["products_table_name"]
            and runtime_settings["CATALOG_METADATA_TABLE_NAME"] == outputs["catalog_metadata_table_name"],
            "Runtime catalog differs from the selected deployment")
    guardrail = {"id": runtime_settings["GUARDRAIL_ID"], "version": runtime_settings["GUARDRAIL_VERSION"]}
    report["account"] = caller["Account"]
    report["region"] = outputs["aws_region"]
    report["guardrail"] = guardrail
    report["settings"] = [
        config.MODEL_CONFIG, config.FAST_MODEL_CONFIG,
        config.INGREDIENT_MODEL_CONFIG, config.EXPLANATION_MODEL_CONFIG,
    ]

    def model(settings):
        options = {key: value for key, value in settings.items() if key != "region_name"}
        return GuardedBedrockModel(
            boto_session=session, **options,
            boto_client_config=Config(read_timeout=150, retries={"total_max_attempts": 1}),
            guardrail_id=guardrail["id"], guardrail_version=guardrail["version"],
            guardrail_stream_processing_mode="sync",
        )

    def check(name, action):
        row = {"name": name, "status": "RUNNING"}
        report["checks"].append(row)
        started = time.monotonic()
        try:
            details = action()
            row.update(status="PASS", **(details or {}))
        except Exception as exc:
            row.update(status="FAIL", error_type=type(exc).__name__, reason=str(exc))
        finally:
            row["seconds"] = round(time.monotonic() - started, 3)
            args.report.write_text(json.dumps(report, indent=2, default=str) + "\n")
            print(json.dumps(row), flush=True)

    for schema, value, settings in fixtures():
        def output_contract(schema=schema, value=value, settings=settings):
            agent = Agent(
                model=model(settings), structured_output_model=schema, callback_handler=None,
                system_prompt="This is a software contract test using supplied fictional data. "
                "Call the structured output tool with the supplied JSON unchanged.",
            )
            result = agent(json.dumps(value), limits={"turns": 4})
            expected = schema.model_validate(value)
            actual = result.structured_output
            require(actual == expected, f"Fixture changed: expected {expected!r}; received {actual!r}")
            return {"usage": result.metrics.accumulated_usage}
        mode = "strict" if settings["strict_tools"] else "validated"
        check(f"{mode}_{schema.__name__}", output_contract)

    for settings in (config.MODEL_CONFIG, config.FAST_MODEL_CONFIG):
        def retry_contract(settings=settings):
            async def invoke():
                events = [event async for event in model(settings).structured_output(
                    ContractAnswer,
                    [{"role": "user", "content": [{"text": '{"answer":"ready"}'}]}],
                    system_prompt="Return the supplied JSON using the ContractAnswer tool.",
                )]
                require(events[-1].get("output") == ContractAnswer(answer="ready"), "No valid output")
            asyncio.run(invoke())
        check(f"single_tool_retry_{settings['model_id']}", retry_contract)

    def vision_contract():
        image = BytesIO()
        Image.new("RGB", (64, 64), "red").save(image, format="PNG")
        agent = Agent(
            model=model(config.MODEL_CONFIG), structured_output_model=ContractAnswer,
            callback_handler=None,
        )
        result = agent([
            {"text": "This is a generated color swatch. Return its color as one lowercase word."},
            {"image": {"format": "png", "source": {"bytes": image.getvalue()}}},
        ], limits={"turns": 4})
        require(result.structured_output == ContractAnswer(answer="red"), "Unexpected swatch color")
        return {"usage": result.metrics.accumulated_usage}
    check("synthetic_vision", vision_contract)

    def catalog_contract():
        # This contract runs on the operator's machine over the public regional
        # API. The application's 250/100 ms VPC transport limits are qualified
        # separately by the native probe; do not apply them to an internet hop.
        # CatalogMetadata still enforces its normal overall budget and bounds.
        transport = {"connect_timeout": 0.5, "read_timeout": 0.5}
        report["local_metadata_transport"] = {**transport, "sdk_attempts": 1}
        metadata = CatalogMetadata(
            DynamoReads(session.client(
                "dynamodb", config=Config(**transport, retries={"total_max_attempts": 1}),
            )), table_name=outputs["catalog_metadata_table_name"],
            catalog_id=runtime_settings["CATALOG_ID"],
        )
        # Ingredient tools consume metadata only. Native product retrieval is
        # qualified separately from inside the deployment's private network.
        state = {"product_service": SimpleNamespace(
            metadata=metadata, config=metadata.configuration(),
        )}
        agent = Agent(
            name="ingredients_Cleanser", model=model(config.FAST_MODEL_CONFIG),
            tools=[get_available_ingredients_for_step, resolve_ingredient_names],
            structured_output_model=ContractAnswer, callback_handler=None,
            system_prompt="Resolve exact ingredient identities for a cosmetic cleanser. First use "
            "get_available_ingredients_for_step for Cleanser, then "
            "resolve_ingredient_names for Cleanser with names ['Glycerin']. "
            "After both tools succeed, use ContractAnswer with answer ready.",
        )
        result = agent(
            "I am looking for a cleanser containing glycerin for normal skin.",
            invocation_state=state, limits={"turns": 6},
        )
        names = {
            block["toolUse"]["name"] for message in agent.messages
            for block in message.get("content", []) if "toolUse" in block
        }
        require({"get_available_ingredients_for_step", "resolve_ingredient_names"} <= names,
                "Both catalog tools must be invoked")
        require(not state.get("tool_errors"), "Catalog tool reported an error")
        require(2 <= state.get("discovery_calls", {}).get("ingredients_Cleanser", 0) <= 3,
                "Ingredient discovery exceeded its bounded contract")
        resolved = metadata.resolve_names(("Glycerin",), state["product_service"].config.taxonomy_version)
        require(len(resolved) == 1 and resolved[0].get("status") == "resolved"
                and bool(resolved[0].get("ingredient_id")),
                "Published ingredient registry did not resolve Glycerin")
        require(result.structured_output == ContractAnswer(answer="ready"), "No final output")
        return {"usage": result.metrics.accumulated_usage}
    check("native_ingredient_tools_and_tool_results", catalog_contract)

    def production_ingredient_contract():
        metadata = CatalogMetadata(
            DynamoReads(session.client("dynamodb", config=Config(
                connect_timeout=0.5, read_timeout=0.5, retries={"total_max_attempts": 1},
            ))), table_name=outputs["catalog_metadata_table_name"],
            catalog_id=runtime_settings["CATALOG_ID"],
        )
        service = SimpleNamespace(metadata=metadata, config=metadata.configuration())
        category = "Cleanser"
        require(category in service.config.categories, "Test catalog needs a Cleanser category")
        state = {"product_service": service, "preferences": Preferences()}
        # Exercise the real prompt and factory while binding this local probe
        # to the explicitly selected deployment's live model and guardrail.
        with patch("agents.ingredients_analysis_agent.get_ingredient_model",
                   return_value=model(config.INGREDIENT_MODEL_CONFIG)):
            agent = create_ingredients_agent(category)
        result = agent(json.dumps({
            "user_profile": fixtures()[1][1]["user_profile"],
            "routine_steps": [{
                "step_name": category, "justification": "Basic care",
                "why_this_step_for_you": "Maintain comfort", "when": "Morning",
            }],
        }), invocation_state=state, limits={"turns": 6})
        require(not state.get("tool_errors"), "Catalog tool reported an error")
        require(1 <= state.get("discovery_calls", {}).get(f"ingredients_{category}", 0) <= 3,
                "Ingredient discovery must use the bounded catalog tools")
        validated = ProductService.validate_ingredients(
            service, result.structured_output, category, Preferences(),
        )
        require(all(
            text.strip().lower() not in {"", "x", "placeholder"}
            for item in validated.key_ingredients
            for text in (item.benefit, item.why_for_you, item.usage)
        ), "Ingredient narrative must not be blank or a placeholder")
        return {
            "usage": result.metrics.accumulated_usage,
            "model_id": config.INGREDIENT_MODEL_CONFIG["model_id"],
            "strict_tools": config.INGREDIENT_MODEL_CONFIG["strict_tools"],
            "selected_ingredient_ids": [item.ingredient_id for item in validated.key_ingredients],
        }
    check("production_ingredient_selection", production_ingredient_contract)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-model-invocations", action="store_true")
    args = parser.parse_args()
    if not args.allow_model_invocations:
        parser.error("--allow-model-invocations is required; this performs billable Bedrock requests")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(), "revision": args.revision,
        "scope": "Local application code; live Bedrock and test catalog; synthetic data only",
        "checks": [],
    }
    try:
        run(args, report)
    finally:
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return any(row["status"] != "PASS" for row in report["checks"])


if __name__ == "__main__":
    raise SystemExit(main())
