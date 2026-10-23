"""Resolve model-selected IDs only against this node's trusted catalog query."""

import re

from .models import ProductAnalysisOutput, ProductDetail


def safe_product_image(value: object) -> str:
    """Product images are published assets on the application's own origin."""
    if isinstance(value, str) and re.fullmatch(
        r"/products/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)", value
    ):
        return value
    return ""


def bind_products(
    output: ProductAnalysisOutput, node_id: str, trusted_queries: dict,
) -> ProductAnalysisOutput:
    if node_id != f"products_{output.step_name}":
        raise ValueError("Product output does not match its assigned step")
    catalog = trusted_queries.get(node_id, {})
    ids = [product.product_id for product in output.top_recommendations]
    if not ids or len(ids) != len(set(ids)) or any(product_id not in catalog for product_id in ids):
        raise ValueError("Product selection is absent from this node's catalog query")
    products = []
    for selection in output.top_recommendations:
        record = catalog[selection.product_id]
        products.append(ProductDetail(
            product_id=selection.product_id,
            name=record["product_name"],
            price=record["price"],
            match_score=record["match_score"],
            image_url=safe_product_image(record["image_url"]),
            matched_ingredients=record["matched_ingredients"],
            # Generated explanation is plain text; it cannot supply catalog facts.
            why_for_you=selection.why_for_you,
            usage_tip=selection.usage_tip,
        ))
    return ProductAnalysisOutput(step_name=output.step_name, top_recommendations=products)
