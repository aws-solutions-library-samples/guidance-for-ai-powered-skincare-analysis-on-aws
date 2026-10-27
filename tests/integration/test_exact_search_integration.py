"""Real adapter/service/repository composition with substituted network boundaries."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from agents.search.budget import SearchBudget
from agents.search.errors import InvalidSearchResponse, SearchDeadlineExceeded, SearchUnavailable
from agents.search.opensearch_adapter import OpenSearchExactAdapter
from agents.search.repository import CanonicalProductRepository
from agents.search.service import ExactSearchService
from tests.search_fixtures import (
    configuration, dynamo_resource, engine_response, product, readiness, request,
)


def make_service(records, response=None, canonical_rows=None):
    config = configuration()
    client = Mock()
    client.transport.max_retries = 0
    client.search.return_value = response if response is not None else engine_response(records)
    resource = dynamo_resource()
    resource.batch_get_item.return_value = {
        "Responses": {"products": canonical_rows if canonical_rows is not None else [
            record.model_dump(mode="json") for record in records
        ]},
    }
    repository = CanonicalProductRepository(resource, table_name="products", catalog_id="fixture")
    adapter = OpenSearchExactAdapter(client, config)
    service = ExactSearchService(config, adapter, repository, wall_clock=lambda: 1000)
    return service, client, resource


def test_full_exact_search_uses_one_query_and_strong_id_reads_preserving_order():
    records = [product(f"product-{i:03}") for i in range(4)]
    service, client, resource = make_service(
        records, canonical_rows=[record.model_dump(mode="json") for record in reversed(records)],
    )
    result = service.search(request(), readiness=readiness())
    assert [item.product.product_id for item in result.products] == [
        "product-000", "product-001", "product-002",
    ]
    assert all(item.matched_count == 3 and item.preferred_count == 3 for item in result.products)
    assert result.trace.hydrated == 4
    assert client.search.call_count == 1
    call = resource.batch_get_item.call_args.kwargs["RequestItems"]["products"]
    assert call["ConsistentRead"] is True
    assert len(call["Keys"]) == 4
    resource.Table.assert_not_called()


def test_complete_zero_hits_need_no_second_query_or_canonical_read():
    service, client, resource = make_service([])
    result = service.search(request(), readiness=readiness())
    assert result.status == "no_match" and result.reason == "no_matching_products"
    assert result.products == ()
    assert client.search.call_count == 1
    resource.batch_get_item.assert_not_called()


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(timed_out=True),
    lambda value: value["_shards"].update(successful=1),
    lambda value: value["_shards"].update(failed=1),
    lambda value: value.update(terminated_early=True),
    lambda value: value["hits"]["hits"][0].update(_score=2.5),
    lambda value: value["hits"]["hits"][0].update(_score=True),
    lambda value: value["hits"]["hits"][0].update(_index="wrong-generation"),
    lambda value: value["hits"]["hits"][0]["_source"].update(catalog_id="other"),
])
def test_partial_or_malformed_engine_responses_cannot_become_no_match(mutate):
    records = [product()]
    response = engine_response(records)
    mutate(response)
    service, _, resource = make_service(records, response=response)
    with pytest.raises(InvalidSearchResponse):
        service.search(request(), readiness=readiness())
    resource.batch_get_item.assert_not_called()


def test_changed_canonical_candidates_have_distinct_catalog_changed_reason():
    old = product()
    newer = product(source_revision=2, ingredient_ids=["ing-other"])
    service, client, _ = make_service([old], canonical_rows=[newer.model_dump(mode="json")])
    result = service.search(request(), readiness=readiness())
    assert result.reason == "catalog_changed"
    assert result.trace.dropped_changed == 1
    assert client.search.call_count == 1


def test_display_only_change_is_hydrated_but_count_mismatch_is_an_error():
    old = product()
    newer = product(source_revision=2, name="New catalog name")
    service, _, _ = make_service([old], canonical_rows=[newer.model_dump(mode="json")])
    assert service.search(request(), readiness=readiness()).products[0].product.name == "New catalog name"
    service, _, _ = make_service([old], response=engine_response([old], [2]))
    with pytest.raises(InvalidSearchResponse, match="count"):
        service.search(request(), readiness=readiness())


def test_one_refill_is_bounded_to_original_candidates_and_no_pagination():
    records = [product(f"product-{i:03}") for i in range(100)]
    service, client, resource = make_service(records)
    resource.batch_get_item.side_effect = [
        {"Responses": {"products": []}},
        {"Responses": {"products": [row.model_dump(mode="json") for row in records[10:]]}},
    ]
    result = service.search(request(), readiness=readiness())
    assert result.products[0].product.product_id == "product-010"
    assert result.trace.hydrated == 100 and result.trace.hydration_batches == 2
    assert [len(call.kwargs["RequestItems"]["products"]["Keys"])
            for call in resource.batch_get_item.call_args_list] == [10, 90]
    assert client.search.call_count == 1


def test_unprocessed_keys_are_retried_once_without_skipping_higher_ranked_product():
    first, second = product("product-001"), product("product-002")
    service, _, resource = make_service([first, second])
    resource.batch_get_item.side_effect = [
        {"Responses": {"products": [second.model_dump(mode="json")]},
         "UnprocessedKeys": {"products": {"Keys": [{"product_id": first.product_id}]}}},
        {"Responses": {"products": [first.model_dump(mode="json")]}},
    ]
    result = service.search(request(), readiness=readiness())
    assert result.products[0].product.product_id == first.product_id
    assert result.trace.dependency_retries == 1
    assert resource.batch_get_item.call_args.kwargs["RequestItems"]["products"]["Keys"] == [
        {"product_id": first.product_id},
    ]


def test_unresolved_keys_never_count_as_absent_or_allow_successful_short_list():
    first, second = product("product-001"), product("product-002")
    service, _, resource = make_service([first, second])
    resource.batch_get_item.side_effect = [
        {"Responses": {"products": [second.model_dump(mode="json")]},
         "UnprocessedKeys": {"products": {"Keys": [{"product_id": first.product_id}]}}},
        {"Responses": {}, "UnprocessedKeys": {"products": {"Keys": [{"product_id": first.product_id}]}}},
    ]
    with pytest.raises(SearchUnavailable):
        service.search(request(), readiness=readiness())
    assert resource.batch_get_item.call_count == 2


def test_final_validation_removes_changed_product_without_searching_again():
    old = product()
    service, client, resource = make_service([old])
    result = service.search(request(), readiness=readiness())
    resource.batch_get_item.return_value = {"Responses": {"products": [
        product(source_revision=2, is_deleted=True).model_dump(mode="json"),
    ]}}
    final = service.finalize((result,), budget=SearchBudget())
    assert final[0].products == () and final[0].reason == "catalog_changed"
    assert client.search.call_count == 1


@pytest.mark.parametrize("observation", [
    {"healthy": False}, {"source_healthy": False}, {"checked_at": 939},
    {"checked_at": 1001}, {"oldest_pending_at": 700}, {"catalog_id": "other"},
])
def test_bad_readiness_rejects_before_any_product_search(observation):
    service, client, _ = make_service([])
    with pytest.raises(SearchUnavailable):
        service.search(request(), readiness=readiness(**observation))
    client.search.assert_not_called()


def test_scheduled_queue_time_consumes_the_same_deadline():
    budget = SearchBudget(clock=lambda: 10.0, started=8.0)
    service, client, _ = make_service([])
    with pytest.raises(SearchDeadlineExceeded):
        service.search(request(), readiness=readiness(), budget=budget)
    client.search.assert_not_called()


def test_real_boto_decimal_integers_are_valid_but_fractional_revisions_are_not():
    record = product()
    row = record.model_dump(mode="json")
    row["source_revision"] = Decimal("1")
    row["price_minor"] = Decimal("1000")
    service, _, _ = make_service([record], canonical_rows=[row])
    assert service.search(request(), readiness=readiness()).products
    row["source_revision"] = Decimal("1.5")
    service, _, _ = make_service([record], canonical_rows=[row])
    with pytest.raises(InvalidSearchResponse):
        service.search(request(), readiness=readiness())
