"""Repository behavior with a fake DynamoDB table, including service failures."""

from unittest.mock import Mock

import pytest

from experiments.search.legacy_repository import ProductService
from catalog import SchemaMapping


@pytest.fixture
def service():
    service = ProductService.__new__(ProductService)
    service.table = Mock()
    service.table_name = "test-products"
    service.schema = SchemaMapping()
    service.currency = "£"
    service.index_name = "product_type-index"
    return service


def test_queries_all_pages_including_empty_page_with_continuation(service):
    service.table.query.side_effect = [
        {"Items": [{"product_name": "first"}], "LastEvaluatedKey": {"id": "a"}},
        {"Items": [], "LastEvaluatedKey": {"id": "b"}},
        {"Items": [{"product_name": "last"}]},
    ]
    assert service.get_products_by_type("Cleanser") == [
        {"product_name": "first"}, {"product_name": "last"},
    ]
    calls = service.table.query.call_args_list
    assert "ExclusiveStartKey" not in calls[0].kwargs
    assert calls[1].kwargs["ExclusiveStartKey"] == {"id": "a"}
    assert calls[2].kwargs["ExclusiveStartKey"] == {"id": "b"}
    assert all(call.kwargs["IndexName"] == "product_type-index" for call in calls)


@pytest.mark.parametrize("method,operation,args", [
    ("has_products", "scan", ()),
    ("get_products_by_type", "query", ("Cleanser",)),
])
def test_database_failure_is_not_reported_as_empty(service, method, operation, args):
    failure = RuntimeError("AccessDenied: datastore unavailable")
    getattr(service.table, operation).side_effect = failure
    with pytest.raises(RuntimeError) as raised:
        getattr(service, method)(*args)
    assert raised.value is failure


@pytest.mark.parametrize("count,expected", [(0, False), (1, True)])
def test_actual_empty_catalog_is_distinguished_from_failure(service, count, expected):
    service.table.scan.return_value = {"Count": count}
    assert service.has_products() is expected


def test_ranking_uses_later_pages_and_catalog_field_mapping(service):
    service.schema = SchemaMapping(
        category_field="category", name_field="name", ingredients_field="inci",
        price_field="cost", image_field="photo",
    )
    service.table.query.side_effect = [
        {"Items": [{"name": "low", "inci": ["water", "glycerin"], "cost": 4}],
         "LastEvaluatedKey": {"id": "next"}},
        {"Items": [{"name": "high", "inci": ["glycerin", "water"], "cost": 8}]},
    ]
    result = service.find_best_products("Cleanser", ["Glycerin"], limit=1)
    assert [product["name"] for product in result] == ["high"]
    assert result[0]["cost"] == "£8.00"
    assert result[0]["matched_ingredients"] == ["Glycerin"]


def test_matching_normalizes_requests_consistently_and_keeps_zero_price(service):
    service.table.query.return_value = {
        "Items": [{"product_name": "Sample", "ingredients": ["glycerin"], "price": 0}],
    }
    product = service.find_best_products("Cleanser", [" Glycerin ", "Glycerin", ""])[0]
    assert product["position_score"] == 1
    assert product["match_score"] == "100.0%"
    assert product["matched_ingredients"] == ["Glycerin"]
    assert product["price"] == "£0.00"


def test_ingredient_frequencies_count_products_not_duplicate_entries(service):
    service.table.query.return_value = {"Items": [
        {"ingredients": [{"S": "glycerin"}, {"S": "glycerin"}, {"S": "water"}]},
        {"ingredients": ["glycerin"]},
    ]}
    assert service.get_available_ingredients("Cleanser", top_n=1) == [
        {"ingredient": "glycerin", "count": 2, "product_count": 2},
    ]
