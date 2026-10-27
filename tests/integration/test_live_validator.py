"""Regression tests for the live checker, using only in-memory events."""

import asyncio
import json

import pytest

from tests.live_sse import iter_events, read_events, run_integration_test, validate_events, validate_timings
from tests.integration.test_pipeline import collect, pipeline, request_payload


@pytest.fixture
def successful_events(pipeline, request_payload):
    events = asyncio.run(collect(request_payload))
    assert validate_events(events) == []
    return events


def test_terminal_error_never_passes(successful_events):
    successful_events[-1] = {"type": "error", "message": "Compilation failed"}
    errors = validate_events(successful_events)
    assert any("Compilation failed" in error for error in errors)


def test_earlier_error_is_not_hidden_by_later_success(successful_events):
    successful_events.insert(2, {"type": "error", "message": "Datastore unavailable"})
    assert validate_events(successful_events)


def test_intermediate_diagnose_result_is_not_terminal_success(successful_events):
    end = next(index for index, event in enumerate(successful_events) if event["type"] == "multiagent_result")
    assert validate_events(successful_events[:end + 1])


def test_failed_final_status_fails(successful_events):
    successful_events[-1]["result"]["status"] = "failed"
    assert validate_events(successful_events)


def test_empty_compiled_routine_fails(successful_events):
    compile_event = next(event for event in successful_events if event.get("node_id") == "compile" and "node_result" in event)
    compile_event["node_result"]["result"]["results"]["compile"]["result"]["message"]["content"] = [
        {"text": json.dumps({"user_profile": {}, "routine_steps": []})}
    ]
    assert validate_events(successful_events)


def test_invalid_data_frame_is_not_silently_ignored():
    class Response:
        def iter_lines(self, **kwargs):
            return iter([": keepalive", "data: not-json"])

    with pytest.raises(ValueError):
        read_events(Response())


def test_sse_frames_preserve_utf8_and_multiline_json():
    event = {"type": "error", "message": "Crème 🌿"}
    payload = json.dumps(event, ensure_ascii=False, indent=2)

    class Response:
        def iter_lines(self, **kwargs):
            return iter([b": heartbeat", *(f"data: {line}".encode() for line in payload.splitlines()), b""])

    assert read_events(Response()) == [event]


def test_reader_yields_before_the_rest_of_the_response_arrives():
    class Response:
        def iter_lines(self, chunk_size):
            assert chunk_size == 1
            yield b'data: {"type": "multiagent_node_start"}'
            yield b""
            raise RuntimeError("Later network read")

    reader = iter_events(Response())
    assert next(reader)["type"] == "multiagent_node_start"
    with pytest.raises(RuntimeError, match="Later network"):
        next(reader)


def test_truncated_frame_fails_even_if_json_is_valid():
    class Response:
        def iter_lines(self, **kwargs):
            yield b'data: {"type": "multiagent_result"}'

    with pytest.raises(ValueError, match="inside an SSE frame"):
        read_events(Response())


def test_timing_checker_rejects_buffered_success_and_long_idle_gap():
    events = [{"type": "multiagent_node_stop"}] * 3
    assert validate_timings(events, [1, 5, 10]) == []
    assert validate_timings(events, [10, 10.001, 10.002])
    assert validate_timings(events, [31, 40, 50])
    assert validate_timings(events, [1, 62, 80])


def test_http_failure_returns_false_without_reading_success(monkeypatch):
    import requests

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            raise requests.HTTPError("401 Unauthorized")

    monkeypatch.setattr("tests.live_sse.requests.post", lambda *args, **kwargs: Response())
    assert not run_integration_test("https://example.invalid", "dummy", "image")
