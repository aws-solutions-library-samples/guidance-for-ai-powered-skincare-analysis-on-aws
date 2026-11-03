"""Native IAM clients with verified TLS, private endpoints and bounded retries."""

import math
from urllib.parse import urlsplit
from decimal import Decimal
from types import SimpleNamespace

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.config import Config
from opensearchpy import OpenSearch, Urllib3AWSV4SignerAuth, Urllib3HttpConnection

DYNAMODB_CONNECT_TIMEOUT = 0.250
DYNAMODB_READ_TIMEOUT = 0.100
DYNAMODB_CALL_TIMEOUT = DYNAMODB_CONNECT_TIMEOUT + DYNAMODB_READ_TIMEOUT


def single_attempt_timeout(resource) -> float:
    """Reserve both connection and read time; retries belong to SearchBudget."""
    config = resource.meta.client.meta.config
    retries = config.retries or {}
    attempts = retries.get("total_max_attempts", retries.get("max_attempts", -1) + 1)
    if attempts != 1:
        raise ValueError("Catalog SDK retries must be disabled")
    timeouts = (config.connect_timeout, config.read_timeout)
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or value <= 0
        for value in timeouts
    ):
        raise ValueError("Catalog connection/read timeouts must be positive and finite")
    return sum(timeouts)


def attribute_map(value: dict) -> dict:
    """Encode native values without boto3 Resource's mutable event handlers."""
    def numbers(item):
        if isinstance(item, float):
            return Decimal(str(item))
        if isinstance(item, (list, tuple)):
            return [numbers(child) for child in item]
        if isinstance(item, dict):
            return {key: numbers(child) for key, child in item.items()}
        return item
    serializer = TypeSerializer()
    return {key: serializer.serialize(numbers(item)) for key, item in value.items()}


def native_map(value: dict) -> dict:
    deserializer = TypeDeserializer()
    return {key: deserializer.deserialize(item) for key, item in value.items()}


class DynamoReads:
    """Share only a low-level client between the graph's worker threads."""

    def __init__(self, client):
        self.client = client
        self.meta = SimpleNamespace(client=client)

    def batch_get_item(self, *, RequestItems: dict) -> dict:
        response = self.client.batch_get_item(RequestItems={
            table: {**spec, "Keys": [attribute_map(key) for key in spec["Keys"]]}
            for table, spec in RequestItems.items()
        })
        if "Responses" not in response:
            raise ValueError("DynamoDB returned no batch response envelope")
        return {
            **response,
            "Responses": {
                table: [native_map(item) for item in items]
                for table, items in response.get("Responses", {}).items()
            },
            "UnprocessedKeys": {
                table: {**spec, "Keys": [native_map(key) for key in spec["Keys"]]}
                for table, spec in response.get("UnprocessedKeys", {}).items()
            },
        }


def dynamodb_resource(session: boto3.Session, *, background=False) -> DynamoReads:
    return DynamoReads(session.client(
        "dynamodb",
        config=Config(
            # Concurrent graph nodes open new TLS connections even after one
            # connection has warmed up. 50ms failed in the native runtime.
            connect_timeout=1 if background else DYNAMODB_CONNECT_TIMEOUT,
            read_timeout=5 if background else DYNAMODB_READ_TIMEOUT,
            retries={"total_max_attempts": 3 if background else 1, "mode": "standard"},
            max_pool_connections=16,
        ),
    ))


def search_client(endpoint: str, session: boto3.Session) -> OpenSearch:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.port not in (None, 443) or parsed.path not in ("", "/")
        or parsed.query or parsed.fragment
        or not parsed.hostname.startswith("vpc-")
        or not parsed.hostname.endswith(".es.amazonaws.com")
    ):
        raise ValueError("Search endpoint must be an HTTPS Amazon OpenSearch VPC domain")
    credentials = session.get_credentials()
    if credentials is None or not session.region_name:
        raise ValueError("Search requires AWS role credentials and an explicit Region")
    return OpenSearch(
        hosts=[{"host": parsed.hostname, "port": 443}],
        http_auth=Urllib3AWSV4SignerAuth(credentials, session.region_name, "es"),
        use_ssl=True, verify_certs=True, ssl_assert_hostname=parsed.hostname,
        connection_class=Urllib3HttpConnection,
        timeout=0.350, max_retries=0, retry_on_timeout=False,
        retry_on_status=(), pool_maxsize=16,
    )
