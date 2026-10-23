"""Explicit live smoke test: python -m tests.live_sse --image /path/to/photo.jpg.

Requires API_URL and AUTH_TOKEN. This invokes the deployed model and can incur
AWS charges. Use an image you are allowed to send to this deployment.
"""

import argparse
import base64
import json
import os
from pathlib import Path

import requests


def _status_succeeded(status):
    return isinstance(status, str) and status.lower() == "completed"


def validate_events(events: list[dict]) -> list[str]:
    """Validate the wire contract independently of any live network request."""
    errors = []
    starts = {event.get("node_id") for event in events if event.get("type") == "multiagent_node_start"}
    stops = {
        event.get("node_id"): event.get("node_result", {})
        for event in events if event.get("type") == "multiagent_node_stop"
    }
    for event in events:
        if event.get("type") == "error":
            errors.append(f"Pipeline error: {event.get('message', 'unspecified')}")

    for node_id in ("skin_analysis", "step_analysis", "compile"):
        if node_id not in starts or node_id not in stops:
            errors.append(f"Missing start/stop for {node_id}")

    plan = stops.get("step_analysis", {}).get("result", {}).get("structured_output", {})
    steps = plan.get("routine_steps", [])
    if not isinstance(steps, list) or not steps:
        errors.append("Missing routine plan")
        steps = []
    for step in steps:
        name = step.get("step_name")
        for prefix, field in (("ingredients", "key_ingredients"), ("products", "top_recommendations")):
            node_id = f"{prefix}_{name}"
            output = stops.get(node_id, {}).get("result", {}).get("structured_output", {})
            if node_id not in starts or not output.get(field) or output.get("step_name") != name:
                errors.append(f"Missing or invalid output for {node_id}")

    for node_id, result in stops.items():
        if not _status_succeeded(result.get("status")):
            errors.append(f"Node {node_id} did not complete successfully")

    if not stops.get("skin_analysis", {}).get("result", {}).get("structured_output"):
        errors.append("Missing skin analysis output")

    if not events or events[-1].get("type") != "multiagent_result":
        errors.append("Stream must end with a successful multiagent_result")
    elif not _status_succeeded((events[-1].get("result") or {}).get("status")):
        errors.append("Final graph result was not successful")

    try:
        compile_result = stops["compile"]["result"]["results"]["compile"]
        if not _status_succeeded(compile_result.get("status")):
            raise ValueError("compile result failed")
        content = compile_result["result"]["message"]["content"]
        routine = json.loads(next(block["text"] for block in content if "text" in block))
        compiled_steps = routine["routine_steps"]
        if not routine["user_profile"] or not compiled_steps:
            raise ValueError("empty routine")
        if [step["step_name"] for step in compiled_steps] != [step["step_name"] for step in steps]:
            raise ValueError("compiled steps do not match plan")
        if any(not step["ingredients"] or not step["products"] for step in compiled_steps):
            raise ValueError("empty recommendations")
    except (KeyError, TypeError, ValueError, StopIteration):
        errors.append("Missing or invalid compiled routine")

    return errors


def read_events(response) -> list[dict]:
    """Read AgentCore SSE frames, rejecting malformed data instead of skipping it."""
    events = []
    data_lines = []

    def flush():
        if not data_lines:
            return
        event = json.loads("\n".join(data_lines))
        data_lines.clear()
        if isinstance(event, str):
            event = json.loads(event)
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("Invalid SSE event")
        events.append(event)

    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line:
            flush()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    flush()
    return events


def run_integration_test(api_url: str, auth_token: str, image_b64: str) -> bool:
    import uuid

    try:
        with requests.post(
            f"{api_url.rstrip('/')}/analyze",
            headers={"Authorization": f"Bearer {auth_token}", "Accept": "text/event-stream"},
            json={"job_id": str(uuid.uuid4()), "images": [image_b64]},
            stream=True,
            timeout=(10, 900),
        ) as response:
            response.raise_for_status()
            events = read_events(response)
        errors = validate_events(events)
    except (requests.RequestException, ValueError, TypeError) as exc:
        print(f"FAIL: {exc}")
        return False
    for error in errors:
        print(f"FAIL: {error}")
    if not errors:
        print(f"PASS: {len(events)} events; complete routine with recommendations")
    return not errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path, help="A real skin photo for this smoke test")
    parser.add_argument("--url", default=os.environ.get("API_URL"))
    args = parser.parse_args()
    token = os.environ.get("AUTH_TOKEN")
    if not args.url or not token:
        parser.error("Set API_URL (or --url) and AUTH_TOKEN")
    image = base64.b64encode(args.image.read_bytes()).decode("ascii")
    raise SystemExit(0 if run_integration_test(args.url, token, image) else 1)


if __name__ == "__main__":
    main()
