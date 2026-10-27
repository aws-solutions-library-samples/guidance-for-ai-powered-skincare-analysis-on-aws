"""Application facade for bounded exact-ingredient catalog access."""

import os
import time
from uuid import uuid4

import boto3

from .errors import AnalysisFailure
from .models import IngredientsAnalysisOutput
from .search.budget import SearchBudget
from .search.catalog import CatalogMetadata
from .search.clients import dynamodb_resource, search_client
from .search.contracts import Preferences, SearchRequest, SearchResult
from .search.opensearch_adapter import OpenSearchExactAdapter
from .search.repository import CanonicalProductRepository
from .search.service import ExactSearchService
from .telemetry import emit_metrics


class ProductService:
    def __init__(self, *, metadata=None, repository=None, client=None):
        if metadata is None or repository is None or client is None:
            session = boto3.Session()
            reads = dynamodb_resource(session)
            catalog_id = os.environ["CATALOG_ID"]
            metadata = CatalogMetadata(
                reads, table_name=os.environ["CATALOG_METADATA_TABLE_NAME"],
                catalog_id=catalog_id,
            )
            repository = CanonicalProductRepository(
                reads, table_name=os.environ["PRODUCTS_TABLE_NAME"], catalog_id=catalog_id,
            )
            client = search_client(os.environ["OPENSEARCH_ENDPOINT"], session)
        self.metadata = metadata
        self.repository = repository
        self.client = client
        self.config = None
        self.search_service = None

    def initialize(self, preferences: Preferences) -> None:
        """Pin one published configuration for the entire routine."""
        self.config = self.metadata.configuration()
        self.search_service = ExactSearchService(
            self.config, OpenSearchExactAdapter(self.client, self.config), self.repository,
        )
        self.search_service.check_readiness(
            self.metadata.readiness(self.config, SearchBudget()),
        )
        try:
            self.config.validate_preferences(preferences)
            ids = sorted(set(preferences.excluded_ingredient_ids).union(
                identifier for entry in preferences.must_have_by_category
                for identifier in entry.ingredient_ids
            ))
            entries = {}
            for start in range(0, len(ids), 20):
                entries.update(self.metadata.ingredients(tuple(ids[start:start + 20]), self.config.taxonomy_version))
            if set(entries) != set(ids):
                raise ValueError("Unknown ingredient constraint")
        except ValueError as exc:
            raise AnalysisFailure("INVALID_PREFERENCES") from exc

    def validate_ingredients(
        self, output: IngredientsAnalysisOutput, category: str, preferences: Preferences,
    ) -> IngredientsAnalysisOutput:
        output = IngredientsAnalysisOutput.model_validate(output.model_dump())
        if output.step_name != category:
            raise ValueError("Ingredient output belongs to another step")
        ids = tuple(item.ingredient_id for item in output.key_ingredients)
        if len(ids) != len(set(ids)) or any(not identifier for identifier in ids):
            raise ValueError("Ingredient output requires distinct canonical IDs")
        entries = self.metadata.ingredients(ids, self.config.taxonomy_version)
        if set(entries) != set(ids):
            raise ValueError("Ingredient output contains an unknown canonical ID")
        ingredients = [
            item.model_copy(update={"name": entries[item.ingredient_id].display_name})
            for item in output.key_ingredients
            if item.ingredient_id not in preferences.excluded_ingredient_ids
        ]
        if not ingredients:
            raise ValueError("Ingredient plan is empty after applying exclusions")
        return output.model_copy(update={"key_ingredients": ingredients})

    def search(
        self, output: IngredientsAnalysisOutput, preferences: Preferences,
        request_id: str, *, scheduled_at: float,
    ) -> SearchResult:
        config = self.config
        budget = SearchBudget(config.step_deadline_seconds, started=scheduled_at)
        request = SearchRequest(
            request_id=request_id, step_id=f"step-{uuid4().hex}",
            catalog_id=config.catalog_id, category_id=output.step_name,
            configuration_id=config.configuration_id, index_generation=config.index_generation,
            taxonomy_version=config.taxonomy_version, eligibility_mode=config.eligibility_mode,
            preferred_ingredient_ids=tuple(item.ingredient_id for item in output.key_ingredients),
            must_have_ingredient_ids=preferences.required_for(output.step_name),
            excluded_ingredient_ids=preferences.excluded_ingredient_ids,
            market=preferences.market or config.default_market,
            currency=preferences.currency or config.default_currency,
            max_price_minor=preferences.max_price_minor,
        )
        result = None
        try:
            readiness = self.metadata.readiness(config, budget)
            result = self.search_service.search(request, readiness=readiness, budget=budget)
            return result
        finally:
            metrics = {
                "StepSearches": (1, "Count"),
                "StepSearchFailures": (int(result is None), "Count"),
                "StepSearchLatency": ((time.monotonic() - scheduled_at) * 1000, "Milliseconds"),
            }
            if result is not None:
                metrics.update({
                    "StepNoMatch": (int(result.status == "no_match"), "Count"),
                    "CandidatesRead": (result.trace.retrieved, "Count"),
                    "CanonicalProductsRead": (result.trace.hydrated, "Count"),
                    "DependencyRetries": (result.trace.dependency_retries, "Count"),
                })
            emit_metrics("step_search", metrics)

    def finalize(self, results: tuple[SearchResult, ...]) -> tuple[SearchResult, ...]:
        budget = SearchBudget()
        self.search_service.check_readiness(self.metadata.readiness(self.config, budget))
        return self.search_service.finalize(results, budget=budget)
