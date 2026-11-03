"""Explicit normalized product fixtures; no inferred stock or ingredient aliases."""

from types import SimpleNamespace
from unittest.mock import Mock

from agents.search.contracts import (
    Candidate, CanonicalProduct, IndexReadiness, SearchConfiguration, SearchRequest,
    matching_hash, record_hash,
)
from agents.search.opensearch_adapter import document_id


def configuration(**changes):
    return SearchConfiguration(
        **{
            "catalog_id": "fixture", "configuration_id": "exact-v1",
            "index_generation": "products-fixture-v1", "taxonomy_version": "fixture-v1",
            "categories": ("Cleanser", "Serum"),
            "default_market": "GB", "default_currency": "GBP",
            "supported_markets": ("GB",), "supported_currencies": ("GBP",),
            **changes,
        }
    )


def request(**changes):
    config = configuration()
    return SearchRequest(
        **{
            "request_id": "request-1", "step_id": "products_Cleanser",
            "catalog_id": config.catalog_id, "configuration_id": config.configuration_id,
            "index_generation": config.index_generation, "taxonomy_version": config.taxonomy_version,
            "category_id": "Cleanser", "preferred_ingredient_ids": ("ing-a", "ing-b", "ing-c"),
            "market": "GB", "currency": "GBP",
            **changes,
        }
    )


def product(product_id="product-001", **changes):
    body = {
        "product_id": product_id, "catalog_id": "fixture", "category_id": "Cleanser",
        "source_revision": 1, "taxonomy_version": "fixture-v1", "schema_version": "2.0",
        "name": "Fixture product", "brand": "", "image_path": "",
        "ingredient_ids": ["ing-a", "ing-b", "ing-c"],
        "raw_ingredients": ["A", "B", "C"], "unresolved_ingredients": [],
        "ingredient_list_complete": True, "ingredient_resolution_complete": True,
        "price_minor": 1000, "currency": "GBP", "market_ids": ["GB"],
        "availability": "unknown", "active": True, "is_deleted": False,
        "source_updated_at": "2026-10-26T00:00:00Z", "ingested_at": "2026-10-26T00:00:00Z",
        "source_provenance": "explicit synthetic test fixture",
        **changes,
    }
    body["matching_hash"] = matching_hash(body)
    body["record_hash"] = record_hash(body)
    return CanonicalProduct.model_validate(body)


def candidate(record, score=3):
    return Candidate(
        product_id=record.product_id, catalog_id=record.catalog_id,
        source_revision=record.source_revision, matching_hash=record.matching_hash,
        score=float(score),
    )


def engine_response(records, scores=None):
    scores = scores or [3] * len(records)
    return {
        "timed_out": False,
        "_shards": {"total": 2, "successful": 2, "failed": 0, "skipped": 0},
        "hits": {"hits": [
            {
                "_id": document_id(record.catalog_id, record.product_id),
                "_index": "products-fixture-v1", "_score": float(score),
                "_source": {
                    field: getattr(record, field) for field in
                    ("catalog_id", "product_id", "source_revision", "matching_hash")
                },
            }
            for record, score in zip(records, scores, strict=True)
        ]},
    }


def readiness(**changes):
    return IndexReadiness(**{
        "catalog_id": "fixture", "configuration_id": "exact-v1",
        "index_generation": "products-fixture-v1",
        "healthy": True, "source_healthy": True, "checked_at": 1000.0,
        **changes,
    })


def dynamo_resource():
    resource = Mock()
    resource.meta.client.meta.config = SimpleNamespace(
        retries={"total_max_attempts": 1}, connect_timeout=0.250, read_timeout=0.100,
    )
    return resource
