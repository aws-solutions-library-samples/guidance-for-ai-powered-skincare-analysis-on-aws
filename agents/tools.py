"""DynamoDB query tools for the skincare graph pipeline.

Tools access ProductService via ToolContext.invocation_state["product_service"].
Failed lookups remain in tool_errors until a same-step retry succeeds, so the
compiler cannot mistake an agent's recovery text for a complete recommendation.
"""

import json
import logging

from strands import ToolContext, tool
from .catalog_binding import safe_product_image

logger = logging.getLogger(__name__)


@tool(context=True)
def get_available_ingredients_for_step(step_name: str, tool_context: ToolContext) -> str:
    """Get available ingredients from the product database for a specific skincare step.

    Args:
        step_name: The skincare step/product category to query (e.g. "Cleanser", "Serum").
        tool_context: Injected ToolContext with invocation_state.

    Returns:
        JSON string with step name, product count, and top ingredients.
    """
    errors = tool_context.invocation_state.setdefault("tool_errors", {})
    node_id = f"ingredients_{step_name}"
    try:
        service = tool_context.invocation_state.get("product_service")
        if not service:
            raise RuntimeError("ProductService not available")

        logger.info(
            "Tool get_available_ingredients_for_step called: step=%r, table=%s",
            step_name,
            getattr(service, "table_name", "UNKNOWN"),
        )

        ingredients = service.get_available_ingredients(
            product_type=step_name, top_n=30
        )

        if not ingredients:
            raise ValueError(f"No ingredients found for step: {step_name}")

        errors.pop(node_id, None)
        return json.dumps(
            {
                "step": step_name,
                "total_products": ingredients[0].get("product_count", 0),
                "top_ingredients": ingredients,
            }
        )
    except Exception as e:
        errors[node_id] = str(e)
        logger.error(
            "Error in get_available_ingredients_for_step: %s", e, exc_info=True
        )
        return json.dumps({"step": step_name, "error": str(e)})


@tool(context=True)
def find_products_for_step(
    step_name: str, required_ingredients: list[str], tool_context: ToolContext
) -> str:
    """Find top products from the database that match required ingredients for a step.

    Args:
        step_name: The skincare step/product category.
        required_ingredients: Nonempty list of required ingredient names.
        tool_context: Injected ToolContext with invocation_state.

    Returns:
        JSON string with step name, matched products, and total found.
    """
    errors = tool_context.invocation_state.setdefault("tool_errors", {})
    node_id = tool_context.agent.name
    trusted = tool_context.invocation_state.setdefault("trusted_products", {})
    try:
        if node_id != f"products_{step_name}":
            raise ValueError("Catalog query does not match the assigned product node")
        service = tool_context.invocation_state.get("product_service")
        if not service:
            raise RuntimeError("ProductService not available")
        if (
            not isinstance(required_ingredients, list)
            or not required_ingredients
            or any(not isinstance(name, str) or not name.strip() for name in required_ingredients)
        ):
            raise ValueError("required_ingredients must be a nonempty list of ingredient names")
        schema = service.schema

        products = service.find_best_products(
            product_type=step_name, required_ingredients=required_ingredients, limit=3
        )

        if not products:
            raise ValueError(f"No products found for step: {step_name}")

        results = [
            {
                "product_id": p["product_id"],
                "product_name": p.get(schema.name_field),
                "price": p.get(schema.price_field),
                "match_score": p.get("match_score"),
                "image_url": safe_product_image(p.get(schema.image_field, "")),
                "ingredients": p.get(schema.ingredients_field, []),
                "matched_ingredients": p.get("matched_ingredients", []),
            }
            for p in products
        ]

        if any(not isinstance(record["product_id"], str) or not record["product_id"] for record in results):
            raise ValueError("Catalog product is missing a stable ID")
        # Separate from model/tool text; only successful repository calls can write it.
        trusted[node_id] = {record["product_id"]: record for record in results}
        errors.pop(node_id, None)
        return json.dumps(
            {"step": step_name, "products": results, "total_found": len(products)}
        )
    except Exception as e:
        errors[node_id] = str(e)
        trusted.pop(node_id, None)
        logger.error("Error in find_products_for_step: %s", e, exc_info=True)
        return json.dumps({"step": step_name, "products": [], "error": str(e)})
