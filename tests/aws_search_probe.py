"""Private qualification Lambda. Included only in the disposable test archive."""

import os
import time
from urllib.error import HTTPError
from urllib.request import urlopen

import boto3
from botocore.exceptions import ClientError
from opensearchpy.exceptions import AuthorizationException

from agents.search.budget import SearchBudget
from agents.search.catalog import CatalogMetadata
from agents.search.clients import dynamodb_resource, search_client
from agents.search.contracts import SearchRequest
from agents.search.opensearch_adapter import OpenSearchExactAdapter
from agents.search.repository import CanonicalProductRepository
from agents.search.service import ExactSearchService


class RecordingAdapter(OpenSearchExactAdapter):
    """Capture the actual bounded retrieval used by selection, without another query."""

    candidates = ()

    def retrieve(self, request, budget):
        self.candidates = super().retrieve(request, budget)
        return self.candidates


def handler(event, context):
    session = boto3.Session()
    endpoint = os.environ["OPENSEARCH_ENDPOINT"]
    search = search_client(endpoint, session)
    resource = dynamodb_resource(session)
    table = os.environ["PRODUCTS_TABLE_NAME"]
    metadata_table = os.environ["CATALOG_METADATA_TABLE_NAME"]
    mode = os.environ["QUALIFICATION_ROLE"]
    if mode == "writer":
        try:
            search.search(index="products-demo-v1", body={"query": {"match_all": {}}},
                          params={"request_timeout": 5})
        except AuthorizationException:
            return {"writer_search_denied": True}
        raise AssertionError("Projection writer was permitted to search")
    metadata = CatalogMetadata(resource, table_name=metadata_table, catalog_id="demo")
    config = metadata.configuration()
    adapter = RecordingAdapter(search, config)
    repository = CanonicalProductRepository(resource, table_name=table, catalog_id="demo")
    service = ExactSearchService(config, adapter, repository)
    # Report cold connections separately; this is a correctness probe, not an SLO.
    started = time.monotonic()
    search.search(index=config.index_generation, body={"query": {"match_none": {}}},
                  params={"request_timeout": 5})
    warmup_ms = (time.monotonic() - started) * 1000
    denied = []
    for label, operation in [
        ("reader_write", lambda: search.index(index=config.index_generation, id="forbidden", body={})),
        ("reader_mget", lambda: search.mget(index=config.index_generation, body={"ids": ["demo/absent"]})),
        ("reader_canonical_scan", lambda: resource.client.scan(TableName=table, Limit=1)),
        ("reader_control_write", lambda: resource.client.put_item(
            TableName=metadata_table, Item={"pk": {"S": "FORBIDDEN"}})),
        ("reader_source_metadata", lambda: metadata.values(("SOURCE",))),
    ]:
        try:
            operation()
        except Exception as exc:
            cause = exc.__cause__ or exc
            if isinstance(cause, AuthorizationException) or (
                isinstance(cause, ClientError)
                and cause.response["Error"]["Code"] in ("AccessDeniedException", "AccessDenied")
            ):
                denied.append(label)
            else:
                raise
        else:
            raise AssertionError(f"Unexpected permission: {label}")
    try:
        with urlopen(f"{endpoint}/{config.index_generation}/_search", timeout=5):
            raise AssertionError("Unsigned private search was accepted")
    except HTTPError as exc:
        assert exc.code == 403, exc.code
        denied.append("unsigned_search")
    requests = event.get("requests", [])
    if not isinstance(requests, list) or not 1 <= len(requests) <= 50:
        raise ValueError("Probe requires 1–50 search cases")
    results = []
    for offset, fields in enumerate(requests):
        wanted = SearchRequest(
            request_id=f"cloud-{offset}", step_id=f"step-{offset}", catalog_id=config.catalog_id,
            configuration_id=config.configuration_id, index_generation=config.index_generation,
            taxonomy_version=config.taxonomy_version, **fields,
        )
        budget = SearchBudget(config.step_deadline_seconds)
        try:
            result = service.search(wanted, readiness=metadata.readiness(config, budget), budget=budget)
        except ValueError as exc:
            # A probe may verify that callers cannot override the catalog's
            # server-owned mode. Preserve the real rejection; never convert it
            # into a successful no-match search or weaken service validation.
            if (wanted.eligibility_mode == config.eligibility_mode
                or str(exc) != "Search request has mismatched eligibility_mode"):
                raise
            results.append({
                "candidate_ids": [], "candidate_counts": [], "ids": [], "counts": [],
                "status": "rejected", "error": str(exc), "trace": None,
            })
            continue
        final = service.finalize((result,), budget=SearchBudget(config.step_deadline_seconds))[0]
        results.append({
            "candidate_ids": [item.product_id for item in adapter.candidates],
            "candidate_counts": [item.score for item in adapter.candidates],
            "ids": [item.product.product_id for item in final.products],
            "counts": [len(item.matched_ingredient_ids) for item in final.products],
            "status": final.status, "trace": result.trace.model_dump(mode="json"),
        })
    return {"generation": config.index_generation, "denied": denied, "warmup_ms": warmup_ms, "results": results}
