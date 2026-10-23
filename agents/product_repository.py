"""DynamoDB-based product service for fast product queries."""

import logging
import os

import boto3
import numpy as np
from boto3.dynamodb.conditions import Key

from catalog import load_catalog

logger = logging.getLogger(__name__)

def _normalize_ingredients(raw_ingredients: list) -> list[str]:
    """Normalize raw DynamoDB ingredient data to a flat string list."""
    if not raw_ingredients:
        return []
    if isinstance(raw_ingredients[0], dict):
        return [item.get("S", "") for item in raw_ingredients]
    return list(raw_ingredients)


def _compute_position_scores(
    products_ingredients: list[list[str]],
    required_ingredients: list[str],
) -> np.ndarray:
    """Compute weighted position scores for all products using vectorized ops.

    For each product, scores each required ingredient by its position in the
    INCI list using harmonic weighting: weight = 1 / (position + 1).
    Ingredients listed first (higher concentration) contribute more to the score.

    Args:
        products_ingredients: List of ingredient lists (one per product), lowercase.
        required_ingredients: List of required ingredient names, lowercase.

    Returns:
        1D array of shape (n_products,) with the total weighted score per product.
    """
    n_products = len(products_ingredients)
    n_required = len(required_ingredients)

    if n_products == 0 or n_required == 0:
        return np.zeros(n_products)

    # Score matrix: (n_products, n_required)
    scores = np.zeros((n_products, n_required), dtype=np.float64)

    for p_idx, ingredients in enumerate(products_ingredients):
        # Build position lookup for this product's ingredients
        position_map: dict[str, int] = {}
        for pos, ing in enumerate(ingredients):
            if ing not in position_map:
                position_map[ing] = pos

        for r_idx, req in enumerate(required_ingredients):
            # Substring match: find the earliest position where req appears
            best_pos: int | None = None
            for ing, pos in position_map.items():
                if req in ing:
                    if best_pos is None or pos < best_pos:
                        best_pos = pos
            if best_pos is not None:
                scores[p_idx, r_idx] = 1.0 / (best_pos + 1)

    # Total score per product = sum of weighted matches
    return scores.sum(axis=1)


class ProductService:
    """Fast product queries using DynamoDB, driven by catalog.yaml schema mapping."""

    def __init__(self, table_name: str | None = None) -> None:
        self.dynamodb = boto3.resource("dynamodb")
        if table_name is None:
            table_name = os.environ.get(
                "PRODUCTS_TABLE_NAME", "smart-beauty-SkincareProducts"
            )
        self.table_name = table_name
        self.table = self.dynamodb.Table(table_name)

        catalog = load_catalog()
        self.schema = catalog.schema
        self.currency = catalog.currency
        self.index_name = f"{self.schema.category_field}-index"

        logger.info("ProductService initialized with table: %s", table_name)

    def has_products(self) -> bool:
        """Check for any products; database failures propagate to the caller."""
        response = self.table.scan(Limit=1, Select="COUNT")
        return response.get("Count", 0) > 0

    def get_products_by_type(self, product_type: str) -> list[dict]:
        """Get all query pages for a product type; database failures propagate.

        Args:
            product_type: The product type/category to query (e.g. "Cleanser").

        Returns:
            List of product dicts from DynamoDB.
        """
        query = {
            "IndexName": self.index_name,
            "KeyConditionExpression": Key(self.schema.category_field).eq(product_type),
        }
        items: list[dict] = []
        while True:
            response = self.table.query(**query)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            query["ExclusiveStartKey"] = last_key

        logger.info("Found %d products for category %r", len(items), product_type)
        return items

    def find_best_products(
        self,
        product_type: str,
        required_ingredients: list[str],
        limit: int = 3,
    ) -> list[dict]:
        """Find top products matching required ingredients using position-weighted scoring.

        Algorithm (two-stage):
        1. Fetch all products of the given type from DynamoDB (GSI query).
        2. Score each product using harmonic positional weighting:
           score = sum(1/(position+1)) for each matched required ingredient.
           Ingredients higher in the INCI list (= higher concentration) contribute
           more to the score.
        3. Return the top N products sorted by weighted score descending.
        """
        products = self.get_products_by_type(product_type)

        if not products:
            return []

        required_ingredients = list(dict.fromkeys(
            ing.strip() for ing in required_ingredients if ing.strip()
        ))
        required_lower = [ing.lower() for ing in required_ingredients]

        # Prepare ingredient lists for vectorized scoring
        products_ingredients: list[list[str]] = []
        for product in products:
            raw = product.get(self.schema.ingredients_field, [])
            normalized = _normalize_ingredients(raw)
            lower = [ing.lower().strip() for ing in normalized if ing]
            products_ingredients.append(lower)
            product[self.schema.ingredients_field] = normalized

        # Vectorized position-weighted scoring
        scores = _compute_position_scores(products_ingredients, required_lower)

        # Compute match metadata and format results
        for idx, product in enumerate(products):
            ingredients_lower = products_ingredients[idx]

            matched = [
                req
                for req in required_ingredients
                if any(req.lower() in ing for ing in ingredients_lower)
            ]
            match_pct = (len(matched) / len(required_ingredients) * 100) if required_ingredients else 0

            product["match_score"] = f"{match_pct:.1f}%"
            product["position_score"] = float(scores[idx])
            product["matched_ingredients"] = matched

            price = product.get(self.schema.price_field)
            if price is not None:
                try:
                    price_val = float(price)
                    product[self.schema.price_field] = (
                        f"{self.currency}{price_val:.2f}"
                    )
                except (ValueError, TypeError):
                    product[self.schema.price_field] = "Price unavailable"
            else:
                product[self.schema.price_field] = "Price unavailable"

        # Sort by position_score (accounts for both presence AND concentration)
        products.sort(key=lambda p: p["position_score"], reverse=True)
        return products[:limit]

    def get_available_ingredients(
        self, product_type: str, top_n: int = 30
    ) -> list[dict]:
        """Get most common ingredients for a product type.

        Returns the top N ingredients sorted by frequency, along with
        the total product count for context.
        """
        products = self.get_products_by_type(product_type)

        ingredient_counts: dict[str, int] = {}
        for product in products:
            ingredients = _normalize_ingredients(
                product.get(self.schema.ingredients_field, [])
            )
            for ingredient in dict.fromkeys(ingredients):
                ingredient_counts[ingredient] = ingredient_counts.get(ingredient, 0) + 1

        sorted_ingredients = sorted(
            ingredient_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        return [
            {"ingredient": ing, "count": count, "product_count": len(products)}
            for ing, count in sorted_ingredients[:top_n]
        ]
