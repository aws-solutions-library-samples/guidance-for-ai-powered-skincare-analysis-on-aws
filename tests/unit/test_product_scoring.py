"""Tests for product position-weighted scoring algorithm."""

import numpy as np
import pytest

from experiments.search.legacy_repository import _compute_position_scores, _normalize_ingredients


class TestNormalizeIngredients:
    def test_flat_list(self):
        assert _normalize_ingredients(["a", "b", "c"]) == ["a", "b", "c"]

    def test_dynamodb_map_format(self):
        raw = [{"S": "niacinamide"}, {"S": "glycerin"}]
        assert _normalize_ingredients(raw) == ["niacinamide", "glycerin"]

    def test_empty_list(self):
        assert _normalize_ingredients([]) == []


class TestPositionScoring:
    """Test the harmonic position-weighted scoring algorithm."""

    def test_earlier_position_scores_higher(self):
        """Product with ingredient at position 0 should outscore position 9."""
        products = [
            ["niacinamide", "glycerin", "water"],  # match at position 0
            ["glycerin", "water", "allantoin", "panthenol", "niacinamide"],  # match at position 4
        ]
        required = ["niacinamide"]
        scores = _compute_position_scores(products, required)

        assert scores[0] > scores[1]
        assert scores[0] == pytest.approx(1.0)  # 1/(0+1)
        assert scores[1] == pytest.approx(0.2)  # 1/(4+1)

    def test_all_matches_early_beats_all_matches_late(self):
        """Product C (positions 0,1,2) > Product A (0,2,3) > Product B (2,8,9)."""
        products = [
            ["niacinamide", "glycerin", "retinol", "squalane", "allantoin"],
            ["glycerin", "water", "squalane", "allantoin", "panthenol",
             "vitamin e", "zinc", "ceramide", "niacinamide", "retinol"],
            ["retinol", "niacinamide", "squalane", "glycerin", "tocopherol"],
        ]
        required = ["niacinamide", "retinol", "squalane"]
        scores = _compute_position_scores(products, required)

        # C > A > B
        assert scores[2] > scores[0] > scores[1]

    def test_no_matches_scores_zero(self):
        products = [["glycerin", "water", "allantoin"]]
        required = ["retinol", "niacinamide"]
        scores = _compute_position_scores(products, required)

        assert scores[0] == 0.0

    def test_empty_products(self):
        scores = _compute_position_scores([], ["niacinamide"])
        assert len(scores) == 0

    def test_empty_required(self):
        products = [["glycerin", "water"]]
        scores = _compute_position_scores(products, [])
        assert scores[0] == 0.0

    def test_substring_match(self):
        """'hyaluronic acid' should match 'sodium hyaluronate' via substring."""
        products = [["sodium hyaluronate", "glycerin"]]
        required = ["hyaluron"]
        scores = _compute_position_scores(products, required)

        assert scores[0] == pytest.approx(1.0)  # matched at position 0

    def test_harmonic_weight_values(self):
        """Verify exact harmonic weights: 1/1, 1/2, 1/3, 1/4..."""
        products = [["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]]
        required = ["a", "c", "f", "j"]
        scores = _compute_position_scores(products, required)

        expected = 1/1 + 1/3 + 1/6 + 1/10  # positions 0, 2, 5, 9
        assert scores[0] == pytest.approx(expected)

    def test_scales_with_many_products(self):
        """Verify scoring works at scale (1000 products)."""
        np.random.seed(42)
        ingredient_pool = [f"ingredient_{i}" for i in range(100)]

        products = []
        for _ in range(1000):
            n_ings = np.random.randint(5, 20)
            ings = list(np.random.choice(ingredient_pool, size=n_ings, replace=False))
            products.append(ings)

        required = ["ingredient_0", "ingredient_5", "ingredient_10"]
        scores = _compute_position_scores(products, required)

        assert scores.shape == (1000,)
        assert scores.max() > 0
        assert scores.min() >= 0

    def test_duplicate_ingredient_uses_first_position(self):
        """If an ingredient appears twice, use the earlier (higher concentration) position."""
        products = [["glycerin", "niacinamide", "water", "niacinamide"]]
        required = ["niacinamide"]
        scores = _compute_position_scores(products, required)

        # Should use position 1 (first occurrence), not position 3
        assert scores[0] == pytest.approx(1/2)
