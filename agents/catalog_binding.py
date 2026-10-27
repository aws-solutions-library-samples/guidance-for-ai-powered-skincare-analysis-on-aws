"""Render server-selected products; generated text cannot change their facts."""

import re
from decimal import Decimal

from .models import ProductAnalysisOutput, ProductDetail, ProductExplanations
from .search.contracts import SearchResult


def safe_product_image(value: object) -> str:
    if isinstance(value, str) and re.fullmatch(
        r"/products/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)", value
    ):
        return value
    return ""


def render_products(
    result: SearchResult, names: dict[str, str], explanations: ProductExplanations | None = None,
    *, explanation_hashes: dict[str, str] | None = None,
    currency_minor_units: dict[str, int] | None = None,
) -> ProductAnalysisOutput:
    currency_minor_units = currency_minor_units if currency_minor_units is not None else {"GBP": 2, "EUR": 2, "USD": 2}
    approved_ids = [item.product.product_id for item in result.products]
    if explanations is not None and (
        explanations.step_name != result.request.category_id
        or [item.product_id for item in explanations.products] != approved_ids
    ):
        raise ValueError("Explanations must preserve every approved product ID in order")
    text = {item.product_id: item for item in explanations.products} if explanations else {}
    products = []
    for selected in result.products:
        product = selected.product
        explanation = text.get(product.product_id)
        # Any changed source content invalidates the previous generated explanation.
        if explanation and (explanation_hashes or {}).get(product.product_id) != product.record_hash:
            explanation = None
        price = "Price unavailable"
        if product.price_minor is not None and product.currency:
            exponent = currency_minor_units.get(product.currency)
            price = (
                f"{product.currency} {Decimal(product.price_minor).scaleb(-exponent):.{exponent}f}"
                if exponent is not None else f"{product.currency} {product.price_minor} minor units"
            )
        products.append(ProductDetail(
            product_id=product.product_id, name=product.name,
            price=price,
            match_score=f"{selected.matched_count / selected.preferred_count * 100:.1f}%",
            image_url=safe_product_image(product.image_path),
            matched_ingredients=[names[identifier] for identifier in selected.matched_ingredient_ids],
            matched_ingredient_ids=list(selected.matched_ingredient_ids),
            matched_must_have_ingredient_ids=list(selected.matched_must_have_ingredient_ids),
            matched_count=selected.matched_count, preferred_count=selected.preferred_count,
            availability=product.availability,
            price_minor=product.price_minor, currency=product.currency,
            why_for_you=explanation.why_for_you if explanation else (
                f"Contains {selected.matched_count} of your {selected.preferred_count} selected ingredients."
            ),
            usage_tip=explanation.usage_tip if explanation else "Follow the product label.",
        ))
    return ProductAnalysisOutput(
        step_name=result.request.category_id, status=result.status, reason=result.reason,
        top_recommendations=products,
    )
