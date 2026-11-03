"""Regression coverage for cold DynamoDB connections and shared deadlines."""

from types import SimpleNamespace

import boto3
import pytest

from agents.search.budget import SearchBudget
from agents.search.catalog import CatalogMetadata
from agents.search.clients import dynamodb_resource
from agents.search.errors import SearchDeadlineExceeded, SearchUnavailable
from agents.search.repository import CanonicalProductRepository
from tests.search_fixtures import dynamo_resource


@pytest.fixture(params=["metadata", "products"])
def read_case(request):
    resource = dynamo_resource()
    if request.param == "metadata":
        reader = CatalogMetadata(resource, table_name="metadata", catalog_id="fixture")
        read = lambda budget: reader.values(("CONFIG",), budget)
        pending = {"metadata": {"Keys": [{"pk": "CONFIG"}]}}
    else:
        reader = CanonicalProductRepository(resource, table_name="products", catalog_id="fixture")
        read = lambda budget: reader.get_by_ids(("product-001",), budget)
        pending = {"products": {"Keys": [{"product_id": "product-001"}]}}
    return SimpleNamespace(resource=resource, read=read, pending=pending)


def test_runtime_transport_allows_cold_tls_without_hidden_sdk_retries():
    session = boto3.Session(
        aws_access_key_id="test-only", aws_secret_access_key="test-only", region_name="us-east-1",
    )
    resource = dynamodb_resource(session)
    try:
        config = resource.client.meta.config
        # A native eight-way cold probe reproduced TLS failures at 50ms.
        assert config.connect_timeout == 0.250
        assert config.read_timeout == 0.100
        assert config.retries["total_max_attempts"] == 1
    finally:
        resource.client.close()


def test_read_reserves_connection_and_response_time_before_io(read_case):
    budget = SearchBudget(seconds=0.300)
    with pytest.raises(SearchDeadlineExceeded):
        read_case.read(budget)
    read_case.resource.batch_get_item.assert_not_called()


def test_slow_successful_read_consumes_the_existing_budget(read_case):
    now = [0.0]
    budget = SearchBudget(clock=lambda: now[0])

    def read(**kwargs):
        now[0] += 0.080
        return {"Responses": {}}

    read_case.resource.batch_get_item.side_effect = read
    assert read_case.read(budget) == {}
    assert budget.remaining() == pytest.approx(1.120)
    assert budget.retries == 0


def test_transport_completion_after_deadline_is_not_success(read_case):
    now = [0.0]
    budget = SearchBudget(clock=lambda: now[0])

    def read(**kwargs):
        now[0] = 1.201
        return {"Responses": {}}

    read_case.resource.batch_get_item.side_effect = read
    with pytest.raises(SearchDeadlineExceeded):
        read_case.read(budget)


def test_unprocessed_retry_cannot_start_without_full_transport_budget(read_case):
    now = [0.0]
    budget = SearchBudget(clock=lambda: now[0], sleep=lambda seconds: None)

    def read(**kwargs):
        now[0] = 0.900
        return {"Responses": {}, "UnprocessedKeys": read_case.pending}

    read_case.resource.batch_get_item.side_effect = read
    with pytest.raises(SearchDeadlineExceeded):
        read_case.read(budget)
    assert read_case.resource.batch_get_item.call_count == 1


def test_unprocessed_keys_share_one_retry_across_metadata_and_products():
    resource = dynamo_resource()
    metadata = CatalogMetadata(resource, table_name="metadata", catalog_id="fixture")
    products = CanonicalProductRepository(resource, table_name="products", catalog_id="fixture")
    budget = SearchBudget(sleep=lambda seconds: None)
    resource.batch_get_item.side_effect = [
        {"Responses": {}, "UnprocessedKeys": {"metadata": {"Keys": [{"pk": "CONFIG"}]}}},
        {"Responses": {}},
        {"Responses": {}, "UnprocessedKeys": {"products": {"Keys": [{"product_id": "p1"}]}}},
    ]
    assert metadata.values(("CONFIG",), budget) == {}
    with pytest.raises(SearchUnavailable, match="retry budget"):
        products.get_by_ids(("p1",), budget)
    assert resource.batch_get_item.call_count == 3
    assert budget.retries == 1


@pytest.mark.parametrize("factory,table", [
    (CatalogMetadata, "metadata"), (CanonicalProductRepository, "products"),
])
@pytest.mark.parametrize("change", [
    {"retries": {"total_max_attempts": 2}},
    {"connect_timeout": 0},
    {"read_timeout": float("inf")},
    {"connect_timeout": float("nan")},
])
def test_invalid_or_retrying_transport_is_rejected(factory, table, change):
    resource = dynamo_resource()
    for name, value in change.items():
        setattr(resource.meta.client.meta.config, name, value)
    with pytest.raises(ValueError):
        factory(resource, table_name=table, catalog_id="fixture")
