"""Offline tests for the live runner's safeguards; these do not test AWS."""

import pytest
from botocore.exceptions import ClientError

from tests.live_release import CheckFailure, direct_runtime_denied, runtime_rejects_corrupt_image, seeded_item, validate_target


def target():
    return {
        "deployment_account_id": "123456789012", "deployment_environment": "test",
        "aws_region": "us-east-1",
        "agentcore_runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example",
        "app_url": "https://example.invalid", "api_url": "https://example.invalid/prod",
    }


@pytest.mark.parametrize("field,value", [
    ("deployment_environment", "prod"),
    ("deployment_account_id", "999999999999"),
    ("aws_region", "eu-west-1"),
    ("app_url", "http://example.invalid"),
    ("app_url", "https://user:secret@example.invalid"),
])
def test_refuses_mismatched_or_unsafe_target(field, value):
    outputs = target()
    outputs[field] = value
    with pytest.raises(CheckFailure):
        validate_target(outputs, "123456789012", "123456789012")


def test_refuses_wrong_authenticated_account():
    with pytest.raises(CheckFailure, match="Account mismatch"):
        validate_target(target(), "123456789012", "999999999999")


def test_accepts_matching_test_target():
    validate_target(target(), "123456789012", "123456789012")


def test_seed_cleanup_runs_on_test_failure_and_has_ownership_condition():
    calls = []

    class Table:
        def put_item(self, **kwargs):
            calls.append(("put", kwargs))

        def delete_item(self, **kwargs):
            calls.append(("delete", kwargs))

    with pytest.raises(RuntimeError):
        with seeded_item(Table(), {"pk": "test-key"}, "run-id"):
            raise RuntimeError("Test failed")
    assert calls[0][1]["ConditionExpression"] == "attribute_not_exists(pk)"
    assert calls[1][1]["ConditionExpression"] == "validation_run = :run"
    assert calls[1][1]["ExpressionAttributeValues"][":run"] == "run-id"


def test_failed_seed_does_not_delete_preexisting_record():
    class Table:
        def put_item(self, **kwargs):
            raise RuntimeError("Already exists")

        def delete_item(self, **kwargs):
            pytest.fail("Must not delete a record this run did not create")

    with pytest.raises(RuntimeError):
        with seeded_item(Table(), {"pk": "test-key"}, "run-id"):
            pytest.fail("Must not run the test without its seed")


@pytest.mark.parametrize("code,passes", [
    ("AccessDeniedException", True), ("ValidationException", False),
    ("ResourceNotFoundException", False), ("ThrottlingException", False),
])
def test_only_explicit_access_denial_passes_direct_runtime_test(code, passes):
    class Client:
        def invoke_agent_runtime(self, **kwargs):
            assert b'"images":[]' in kwargs["payload"]
            raise ClientError({"Error": {"Code": code}}, "InvokeAgentRuntime")

    if passes:
        direct_runtime_denied(Client(), "arn:test")
    else:
        with pytest.raises(CheckFailure):
            direct_runtime_denied(Client(), "arn:test")


@pytest.mark.parametrize("events,passes", [
    ([{"type": "error", "code": "INVALID_INPUT"}], True),
    ([{"type": "error", "code": "SERVICE_UNAVAILABLE"}], False),
    ([{"type": "multiagent_node_start"}, {"type": "error", "code": "INVALID_INPUT"}], False),
])
def test_runtime_probe_requires_early_typed_sse_error(monkeypatch, events, passes):
    import json

    class Response:
        status_code = 200
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_lines(self, **kwargs):
            for event in events:
                yield f"data: {json.dumps(event)}".encode()
                yield b""

    monkeypatch.setattr("tests.live_release.requests.post", lambda *args, **kwargs: Response())
    if passes:
        runtime_rejects_corrupt_image("https://example.invalid", "test-token", {})
    else:
        with pytest.raises(CheckFailure):
            runtime_rejects_corrupt_image("https://example.invalid", "test-token", {})
