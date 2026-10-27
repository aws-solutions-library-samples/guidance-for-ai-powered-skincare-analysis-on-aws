"""Exact keyword count retrieval; no text scoring or model-selected query DSL."""

from typing import Any, Protocol

from .budget import SearchBudget
from .contracts import Candidate, CanonicalProduct, SearchConfiguration, SearchRequest
from .eligibility import filter_query
from .errors import InvalidSearchResponse, SearchUnavailable

CANDIDATE_FIELDS = ("catalog_id", "product_id", "source_revision", "matching_hash")
PROJECTION_FIELDS = (
    *CANDIDATE_FIELDS, "category_id", "schema_version", "taxonomy_version",
    "source_updated_at", "ingested_at", "record_hash", "ingredient_ids",
    "ingredient_list_complete", "ingredient_resolution_complete", "price_minor",
    "currency", "market_ids", "availability", "active", "is_deleted",
)


class SearchClient(Protocol):
    transport: Any

    def search(self, *, index: str, body: dict, params: dict) -> dict: ...


def document_id(catalog_id: str, product_id: str) -> str:
    # A slash cannot occur in either validated identifier.
    return f"{catalog_id}/{product_id}"


def index_mapping() -> dict:
    properties = {
        field: {"type": "keyword"} for field in (
            "catalog_id", "product_id", "category_id", "schema_version",
            "taxonomy_version", "matching_hash", "record_hash", "ingredient_ids",
            "currency", "market_ids", "availability",
        )
    }
    properties.update({
        "source_revision": {"type": "long"},
        "price_minor": {"type": "long"},
        "source_updated_at": {"type": "date"},
        "ingested_at": {"type": "date"},
        **{field: {"type": "boolean"} for field in (
            "ingredient_list_complete", "ingredient_resolution_complete", "active", "is_deleted",
        )},
    })
    return {"mappings": {"dynamic": "strict", "properties": properties}}


def search_document(product: CanonicalProduct) -> dict:
    return product.model_dump(mode="json", include=set(PROJECTION_FIELDS))


def query_body(request: SearchRequest, *, limit: int = 100) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Candidate limit must be between 1 and 100")
    query = filter_query(request)
    query["bool"].update(
        should=[
            {"constant_score": {
                "filter": {"term": {"ingredient_ids": ingredient_id}},
                "boost": 1,
            }}
            for ingredient_id in request.preferred_ingredient_ids
        ],
        minimum_should_match=1,
    )
    return {
        "query": query,
        "size": limit,
        "_source": list(CANDIDATE_FIELDS),
        "track_total_hits": False,
        "sort": [{"_score": "desc"}, {"product_id": "asc"}],
    }


class OpenSearchExactAdapter:
    def __init__(self, client: SearchClient, config: SearchConfiguration) -> None:
        if getattr(getattr(client, "transport", None), "max_retries", None) != 0:
            raise ValueError("OpenSearch SDK retries must be disabled")
        self.client = client
        self.config = config

    def retrieve(self, request: SearchRequest, budget: SearchBudget) -> tuple[Candidate, ...]:
        request.validate_configuration(self.config)
        timeout = min(budget.remaining(), self.config.search_timeout_seconds)
        budget.require(0.001)
        body = query_body(request, limit=self.config.candidate_limit)
        body["timeout"] = f"{max(1, int(timeout * 1000))}ms"
        try:
            response = self.client.search(
                index=self.config.index_generation, body=body,
                params={
                    "allow_partial_search_results": "false",
                    "allow_no_indices": "false",
                    "ignore_unavailable": "false",
                    "request_timeout": timeout,
                },
            )
        except Exception as exc:
            raise SearchUnavailable("Product search failed") from exc
        budget.remaining()
        self._validate_complete(response)
        try:
            hits = response["hits"]["hits"]
            if not isinstance(hits, list) or len(hits) > self.config.candidate_limit:
                raise ValueError("Invalid or oversized hit list")
            candidates = []
            for hit in hits:
                source = hit["_source"]
                if not isinstance(source, dict) or set(source) != set(CANDIDATE_FIELDS):
                    raise ValueError("Invalid candidate source fields")
                if type(hit["_score"]) not in (int, float):
                    raise ValueError("Score is not a JSON number")
                candidate = Candidate.model_validate({**source, "score": hit["_score"]})
                if (
                    candidate.catalog_id != request.catalog_id
                    or hit["_index"] != self.config.index_generation
                    or hit["_id"] != document_id(candidate.catalog_id, candidate.product_id)
                    or candidate.score > len(request.preferred_ingredient_ids)
                ):
                    raise ValueError("Candidate scope, identity, generation or count differs")
                candidates.append(candidate)
            ids = [item.product_id for item in candidates]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate candidate ID")
            if candidates != sorted(candidates, key=lambda item: (-item.score, item.product_id)):
                raise ValueError("Search did not preserve count and ID ordering")
            return tuple(candidates)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidSearchResponse("Invalid product search response") from exc

    @staticmethod
    def _validate_complete(response: dict) -> None:
        if not isinstance(response, dict) or response.get("timed_out") is not False:
            raise InvalidSearchResponse("Search did not complete within its timeout")
        if response.get("terminated_early", False) is not False:
            raise InvalidSearchResponse("Search terminated early")
        shards = response.get("_shards")
        if not isinstance(shards, dict):
            raise InvalidSearchResponse("Search omitted shard completion")
        values = [shards.get(key) for key in ("total", "successful", "failed", "skipped")]
        if any(type(value) is not int or value < 0 for value in values):
            raise InvalidSearchResponse("Invalid shard completion values")
        total, successful, failed, skipped = values
        # OpenSearch counts skipped shards within successful shards.
        if total < 1 or failed or successful != total or skipped > successful:
            raise InvalidSearchResponse("Search did not complete every shard")
