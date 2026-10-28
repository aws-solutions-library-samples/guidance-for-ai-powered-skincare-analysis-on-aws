from types import SimpleNamespace

from botocore.exceptions import ClientError
import pytest

from catalog_worker import handler


def busy():
    return ClientError({
        "Error": {"Code": "TransactionCanceledException", "Message": "Busy"},
        "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}],
    }, "TransactWriteItems")


@pytest.mark.parametrize("entrypoint", [handler.worker, handler.maintenance])
def test_scheduled_work_waits_for_catalog_initialization(monkeypatch, entrypoint):
    reads = []

    def get(key):
        reads.append(key)
        return None

    control = SimpleNamespace(get=get, client=object(), catalog_id="test")
    monkeypatch.setattr(handler, "components", lambda: (control, object()))
    monkeypatch.setenv("CATALOG_OUTBOX_TABLE_NAME", "test-outbox")
    monkeypatch.setenv("PRODUCTS_TABLE_NAME", "test-products")

    def unexpected(*args, **kwargs):
        pytest.fail("Uninitialized scheduled work must not acquire leases or access the index")

    monkeypatch.setattr(handler, "ProjectionWorker", unexpected)
    monkeypatch.setattr(handler, "CatalogMaintenance", unexpected)
    result = entrypoint({"shard": 0}, SimpleNamespace())
    assert result == {"status": "not_initialized"}
    assert reads == ["CONFIG"]


@pytest.fixture
def administration(monkeypatch):
    clock, calls, sleeps = [0.0], [], []
    outcomes = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def initialize(config, registry):
        calls.append((config, registry))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(handler, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=sleep,
    ))
    monkeypatch.setattr(handler, "components", lambda: (object(), object()))
    monkeypatch.setattr(handler, "CatalogAdministration",
                        lambda *args, **kwargs: SimpleNamespace(initialize=initialize))
    for name in ("SEARCH_RUNTIME_ROLE_ARN", "SEARCH_WRITER_ROLE_ARN", "SEARCH_MAINTENANCE_ROLE_ARN"):
        monkeypatch.setenv(name, "arn:aws:iam::123456789012:role/test")
    return outcomes, calls, sleeps, clock


def test_initialize_retries_contention_without_changing_leases(administration):
    outcomes, calls, sleeps, _ = administration
    outcomes.extend([busy(), busy(), {"status": "initialized"}])
    result = handler.admin(
        {"action": "initialize"}, SimpleNamespace(get_remaining_time_in_millis=lambda: 300000),
    )
    assert result == {"status": "initialized"}
    assert len(calls) == 3
    assert sleeps == [1, 1]


def test_initialize_does_not_retry_permission_errors(administration):
    outcomes, calls, sleeps, _ = administration
    error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "Denied"}}, "PutItem")
    outcomes.append(error)
    with pytest.raises(ClientError) as caught:
        handler.admin(
            {"action": "initialize"}, SimpleNamespace(get_remaining_time_in_millis=lambda: 300000),
        )
    assert caught.value is error
    assert len(calls) == 1
    assert sleeps == []


def test_initialize_contention_retry_respects_lambda_time_budget(administration):
    outcomes, calls, sleeps, clock = administration
    outcomes.extend([busy(), busy(), busy()])
    with pytest.raises(ClientError):
        handler.admin(
            {"action": "initialize"}, SimpleNamespace(get_remaining_time_in_millis=lambda: 12000),
        )
    assert len(calls) == 3
    assert sleeps == [1, 1]
    assert clock[0] == 2
