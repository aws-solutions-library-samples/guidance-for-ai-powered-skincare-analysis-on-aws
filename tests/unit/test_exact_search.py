"""Exact-identity/count regressions, including constraints independent of scoring."""

import pytest
from pydantic import ValidationError

from agents.search.contracts import CanonicalProduct, Preferences
from agents.search.eligibility import eligible, matched_ids
from agents.search.opensearch_adapter import index_mapping, query_body
from tests.search_fixtures import product, request


def test_duplicates_positions_and_related_names_do_not_add_preference_matches():
    record = product(ingredient_ids=["ing-a", "ing-a", "ing-b-derivative"])
    query = request(preferred_ingredient_ids=["ing-b", "ing-a", "ing-a"])
    assert query.preferred_ingredient_ids == ("ing-a", "ing-b")
    assert matched_ids(record, query) == ("ing-a",)
    reordered = product(ingredient_ids=["ing-b-derivative", "ing-a"])
    assert matched_ids(reordered, query) == ("ing-a",)
    assert record.matching_hash == reordered.matching_hash


def test_every_must_have_is_required_even_when_it_adds_no_score():
    query = request(must_have_ingredient_ids=["ing-a", "ing-d"])
    assert not eligible(product(), query)
    record = product(ingredient_ids=["ing-a", "ing-b", "ing-d"])
    assert eligible(record, query)
    assert matched_ids(record, query) == ("ing-a", "ing-b")
    mandatory_terms = [
        clause["term"]["ingredient_ids"] for clause in query_body(query)["query"]["bool"]["filter"]
        if "ingredient_ids" in clause.get("term", {})
    ]
    assert mandatory_terms == ["ing-a", "ing-d"]


@pytest.mark.parametrize("changes", [
    {"ingredient_ids": ["ing-a", "ing-x"]},
    {"ingredient_list_complete": False},
    {"ingredient_resolution_complete": False},
    {"ingredient_resolution_complete": False, "unresolved_ingredients": ["unknown"]},
])
def test_exclusions_require_positive_absence_evidence(changes):
    assert not eligible(product(**changes), request(excluded_ingredient_ids=["ing-x"]))


def test_excluded_soft_preference_is_removed_before_denominator():
    query = request(excluded_ingredient_ids=["ing-b"])
    assert query.preferred_ingredient_ids == ("ing-a", "ing-c")
    with pytest.raises(ValidationError):
        request(excluded_ingredient_ids=["ing-a", "ing-b", "ing-c"])


def test_mandatory_constraint_applies_to_only_its_named_category():
    preferences = Preferences(
        must_have_by_category=[{"category_id": "Serum", "ingredient_ids": ["ing-d"]}],
        excluded_ingredient_ids=["ing-x"],
    )
    assert preferences.required_for("Cleanser") == ()
    assert preferences.required_for("Serum") == ("ing-d",)


@pytest.mark.parametrize("fields", [
    {"must_have_by_category": [{"category_id": "Serum", "ingredient_ids": ["ing-a"]}],
     "excluded_ingredient_ids": ["ing-a"]},
    {"must_have_by_category": [
        {"category_id": "Serum", "ingredient_ids": ["ing-a"]},
        {"category_id": "Serum", "ingredient_ids": ["ing-b"]},
    ]},
    {"max_price_minor": True},
    {"max_price_minor": 1.5},
    {"required_families": ["vitamins"]},
    {"query_text": "find something similar"},
])
def test_invalid_public_constraints_are_not_silently_accepted(fields):
    with pytest.raises(ValidationError):
        Preferences.model_validate(fields)


@pytest.mark.parametrize("changes", [
    {"price_minor": None}, {"price_minor": 1001}, {"currency": None},
    {"currency": "EUR"}, {"market_ids": []}, {"active": False}, {"is_deleted": True},
])
def test_unknown_and_boundary_facts_fail_only_the_required_constraints(changes):
    assert not eligible(product(**changes), request(max_price_minor=1000))


def test_budget_equality_zero_price_and_unknown_stock_in_catalog_mode():
    query = request(max_price_minor=1000)
    assert eligible(product(price_minor=1000), query)
    assert eligible(product(price_minor=0), query)
    assert eligible(product(availability="unknown"), query)
    assert not eligible(product(availability="unknown"), request(eligibility_mode="purchasable"))
    assert eligible(product(availability="available"), request(eligibility_mode="purchasable"))
    assert eligible(product(price_minor=None, currency=None, market_ids=[]),
                    request(market=None, currency=None))


def test_product_hash_validation_detects_changed_facts_at_same_revision():
    body = product().model_dump()
    body["price_minor"] = 2000
    with pytest.raises(ValidationError, match="matching hash"):
        CanonicalProduct.model_validate(body)
    body = product().model_dump()
    body["name"] = "Changed display fact"
    with pytest.raises(ValidationError, match="record hash"):
        CanonicalProduct.model_validate(body)


def test_mapping_and_query_have_only_exact_id_scoring():
    body = query_body(request())
    assert body["size"] == 100 and body["track_total_hits"] is False
    assert body["sort"] == [{"_score": "desc"}, {"product_id": "asc"}]
    assert body["query"]["bool"]["minimum_should_match"] == 1
    assert body["query"]["bool"]["should"] == [
        {"constant_score": {"filter": {"term": {"ingredient_ids": value}}, "boost": 1}}
        for value in ("ing-a", "ing-b", "ing-c")
    ]
    properties = index_mapping()["mappings"]["properties"]
    assert properties["ingredient_ids"] == {"type": "keyword"}
    assert not {"retrieval_text", "embedding", "description", "name"} & set(properties)
