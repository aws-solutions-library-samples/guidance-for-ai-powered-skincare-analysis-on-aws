"""Exact-count selection with one bounded refill and authoritative finalization."""

import time
from collections.abc import Callable
from typing import Protocol

from .budget import SearchBudget
from .contracts import (
    Candidate, CanonicalProduct, IndexReadiness, SearchConfiguration, SearchRequest,
    SearchResult, SearchTrace, SelectedProduct,
)
from .eligibility import eligible, matched_ids
from .errors import InvalidSearchResponse, SearchUnavailable


class Retrieval(Protocol):
    config: SearchConfiguration

    def retrieve(self, request: SearchRequest, budget: SearchBudget) -> tuple[Candidate, ...]: ...


class CanonicalReads(Protocol):
    catalog_id: str

    def get_by_ids(
        self, product_ids: tuple[str, ...], budget: SearchBudget,
    ) -> dict[str, CanonicalProduct]: ...


class ExactSearchService:
    def __init__(
        self, config: SearchConfiguration, retrieval: Retrieval,
        repository: CanonicalReads, *, wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if retrieval.config != config or repository.catalog_id != config.catalog_id:
            raise ValueError("Search dependencies have different catalog/configuration")
        self.config = config
        self.retrieval = retrieval
        self.repository = repository
        self.wall_clock = wall_clock

    def check_readiness(self, readiness: IndexReadiness) -> None:
        for field in ("catalog_id", "configuration_id", "index_generation"):
            if getattr(readiness, field) != getattr(self.config, field):
                raise SearchUnavailable("Readiness is for a different configuration")
        now = self.wall_clock()
        age = now - readiness.checked_at
        if not readiness.healthy or not readiness.source_healthy or not 0 <= age <= 60:
            raise SearchUnavailable("Search readiness is missing or stale")
        if readiness.oldest_pending_at is not None and (
            readiness.oldest_pending_at > now or now - readiness.oldest_pending_at >= 300
        ):
            raise SearchUnavailable("Catalog publication is stale")

    def search(
        self, request: SearchRequest, *, readiness: IndexReadiness,
        budget: SearchBudget | None = None,
    ) -> SearchResult:
        request.validate_configuration(self.config)
        budget = budget or SearchBudget(self.config.step_deadline_seconds)
        if budget.deadline - budget.started > self.config.step_deadline_seconds + 1e-9:
            raise ValueError("Caller extended the search deadline")
        budget.remaining()
        self.check_readiness(readiness)
        candidates = self.retrieval.retrieve(request, budget)
        if len(candidates) > self.config.candidate_limit:
            raise InvalidSearchResponse("Too many candidate IDs")
        if len({candidate.product_id for candidate in candidates}) != len(candidates):
            raise InvalidSearchResponse("Duplicate candidates")
        if list(candidates) != sorted(candidates, key=lambda item: (-item.score, item.product_id)):
            raise InvalidSearchResponse("Candidate order violates exact-count ranking")
        selected: list[SelectedProduct] = []
        missing = ineligible = changed = hydrated = batches = 0
        slices = (candidates[:self.config.initial_hydration], candidates[self.config.initial_hydration:])
        for batch in slices:
            if not batch:
                break
            records = self.repository.get_by_ids(tuple(item.product_id for item in batch), budget)
            budget.remaining()
            if set(records) - {item.product_id for item in batch}:
                raise InvalidSearchResponse("Canonical read returned unrequested products")
            hydrated += len(batch)
            batches += 1
            for candidate in batch:
                if candidate.catalog_id != request.catalog_id:
                    raise InvalidSearchResponse("Candidate belongs to another catalog")
                product = records.get(candidate.product_id)
                if product is None:
                    missing += 1
                    continue
                if product.product_id != candidate.product_id or product.catalog_id != request.catalog_id:
                    raise InvalidSearchResponse("Canonical identity differs from indexed identity")
                if product.source_revision < candidate.source_revision:
                    raise InvalidSearchResponse("Indexed revision is newer than canonical source")
                if product.matching_hash != candidate.matching_hash:
                    if product.source_revision == candidate.source_revision:
                        raise InvalidSearchResponse("Same revision has conflicting matching facts")
                    changed += 1
                    continue
                if not eligible(product, request):
                    ineligible += 1
                    continue
                matches = matched_ids(product, request)
                if not matches or candidate.score != len(matches):
                    raise InvalidSearchResponse("Indexed score differs from the exact ingredient count")
                if len(selected) < 3:
                    selected.append(SelectedProduct(
                        product=product,
                        matched_ingredient_ids=matches,
                        matched_must_have_ingredient_ids=request.must_have_ingredient_ids,
                        preferred_count=len(request.preferred_ingredient_ids),
                    ))
            if len(selected) == 3:
                break
        budget.remaining()
        self.check_readiness(readiness)
        return SearchResult(
            request=request,
            status="matched" if selected else "no_match",
            reason=None if selected else ("catalog_changed" if candidates else "no_matching_products"),
            products=tuple(selected),
            trace=SearchTrace(
                retrieved=len(candidates), hydrated=hydrated, hydration_batches=batches,
                dependency_retries=budget.retries, dropped_missing=missing,
                dropped_ineligible=ineligible, dropped_changed=changed,
                elapsed_ms=budget.elapsed_ms,
            ),
        )

    def finalize(
        self, results: tuple[SearchResult, ...], *, budget: SearchBudget,
    ) -> tuple[SearchResult, ...]:
        if len(results) > 8 or len({result.request.step_id for result in results}) != len(results):
            raise ValueError("Finalization requires at most eight distinct steps")
        ids = tuple(dict.fromkeys(
            item.product.product_id for result in results for item in result.products
        ))
        if len(ids) > 24:
            raise ValueError("Too many products for final validation")
        for result in results:
            result.request.validate_configuration(self.config)
        records = self.repository.get_by_ids(ids, budget)
        if set(records) - set(ids):
            raise InvalidSearchResponse("Final reads returned unrequested products")
        finalized = []
        for result in results:
            selected = []
            for previous in result.products:
                product = records.get(previous.product.product_id)
                if product is None:
                    continue
                if product.catalog_id != result.request.catalog_id:
                    raise InvalidSearchResponse("Final record belongs to another catalog")
                if product.source_revision < previous.product.source_revision:
                    raise InvalidSearchResponse("Canonical revision regressed during finalization")
                if product.matching_hash != previous.product.matching_hash:
                    if product.source_revision == previous.product.source_revision:
                        raise InvalidSearchResponse("Same revision changed during finalization")
                    continue
                if not eligible(product, result.request):
                    continue
                selected.append(SelectedProduct(
                    product=product,
                    matched_ingredient_ids=matched_ids(product, result.request),
                    matched_must_have_ingredient_ids=result.request.must_have_ingredient_ids,
                    preferred_count=len(result.request.preferred_ingredient_ids),
                ))
            finalized.append(SearchResult(
                request=result.request,
                status="matched" if selected else "no_match",
                reason=None if selected else (
                    "catalog_changed" if result.products else result.reason
                ),
                products=tuple(selected), trace=result.trace,
            ))
        budget.remaining()
        return tuple(finalized)
