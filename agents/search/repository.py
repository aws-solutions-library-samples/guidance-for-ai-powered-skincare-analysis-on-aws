"""Bounded strongly consistent canonical reads; unprocessed keys are never absent."""

from decimal import Decimal
from typing import Any, Protocol

from .budget import SearchBudget
from .clients import DYNAMODB_CALL_TIMEOUT, single_attempt_timeout
from .contracts import CanonicalProduct
from .errors import InvalidSearchResponse, SearchUnavailable


class DynamoResource(Protocol):
    meta: Any

    def batch_get_item(self, **kwargs: Any) -> dict: ...


def native_numbers(value: Any) -> Any:
    """Decode boto3's Decimal values without accepting fractional integer facts."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Nonfinite DynamoDB number")
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: native_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [native_numbers(item) for item in value]
    return value


class CanonicalProductRepository:
    def __init__(
        self, resource: DynamoResource, *, table_name: str, catalog_id: str,
    ) -> None:
        if not table_name or not catalog_id:
            raise ValueError("Canonical table and catalog ID are required")
        self.call_timeout = single_attempt_timeout(resource)
        if self.call_timeout > DYNAMODB_CALL_TIMEOUT + 1e-9:
            raise ValueError("Canonical connection/read timeout sum must be at most 350ms")
        self.resource = resource
        self.table_name = table_name
        self.catalog_id = catalog_id

    def get_by_ids(
        self, product_ids: tuple[str, ...], budget: SearchBudget,
    ) -> dict[str, CanonicalProduct]:
        if len(product_ids) > 100 or len(set(product_ids)) != len(product_ids):
            raise ValueError("Canonical reads require at most 100 unique IDs")
        if any(not isinstance(key, str) or not key for key in product_ids):
            raise ValueError("Invalid canonical product ID")
        pending = set(product_ids)
        records: dict[str, CanonicalProduct] = {}
        while pending:
            budget.require(self.call_timeout)
            try:
                response = self.resource.batch_get_item(RequestItems={
                    self.table_name: {
                        "Keys": [{"product_id": key} for key in sorted(pending)],
                        "ConsistentRead": True,
                    },
                })
            except Exception as exc:
                raise SearchUnavailable("Canonical product read failed") from exc
            budget.remaining()
            returned, pending = self._parse(response, pending)
            records.update(returned)
            if pending:
                budget.retry()
        return records

    def _parse(
        self, response: dict, requested: set[str],
    ) -> tuple[dict[str, CanonicalProduct], set[str]]:
        try:
            if not isinstance(response, dict):
                raise ValueError("Invalid canonical response")
            responses = response.get("Responses")
            unprocessed_tables = response.get("UnprocessedKeys", {})
            if (
                not isinstance(responses, dict)
                or set(responses) - {self.table_name}
                or not isinstance(unprocessed_tables, dict)
                or set(unprocessed_tables) - {self.table_name}
            ):
                raise ValueError("Unexpected table metadata")
            rows = responses.get(self.table_name, [])
            pending_spec = unprocessed_tables.get(self.table_name, {})
            if not isinstance(rows, list) or not isinstance(pending_spec, dict):
                raise ValueError("Invalid batch rows or pending metadata")
            pending_keys = pending_spec.get("Keys", [])
            if not isinstance(pending_keys, list):
                raise ValueError("Invalid pending key list")
            if self.table_name in unprocessed_tables and not pending_keys:
                raise ValueError("Pending table omitted its keys")
            if pending_spec.get("ConsistentRead", True) is not True:
                raise ValueError("Pending keys changed read consistency")
            pending: set[str] = set()
            for key in pending_keys:
                if not isinstance(key, dict) or set(key) != {"product_id"}:
                    raise ValueError("Invalid pending key")
                identifier = key["product_id"]
                if not isinstance(identifier, str) or identifier not in requested or identifier in pending:
                    raise ValueError("Unrequested or duplicate pending key")
                pending.add(identifier)
            records: dict[str, CanonicalProduct] = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid canonical row")
                product = CanonicalProduct.model_validate(native_numbers(row))
                identifier = product.product_id
                if identifier not in requested or identifier in records or identifier in pending:
                    raise ValueError("Unrequested, duplicate or contradictory canonical row")
                if product.catalog_id != self.catalog_id:
                    raise ValueError("Canonical row is outside this catalog")
                records[identifier] = product
            # Keys absent from both collections were read successfully but do not exist.
            return records, pending
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidSearchResponse("Invalid canonical read response") from exc
