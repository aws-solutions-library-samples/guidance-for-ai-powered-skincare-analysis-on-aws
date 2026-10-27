"""CloudWatch embedded metrics with one bounded deployment dimension."""

import json
import math
import os
import time


def emit_metrics(event: str, values: dict[str, tuple[float, str]], **context):
    deployment = os.environ.get("METRICS_DEPLOYMENT")
    if not deployment:
        return
    if any(not math.isfinite(value) or value < 0 for value, _ in values.values()):
        return
    print(json.dumps({
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "SmartBeauty/ExactSearch",
                "Dimensions": [["Deployment"]],
                "Metrics": [{"Name": name, "Unit": unit} for name, (_, unit) in values.items()],
            }],
        },
        "Deployment": deployment, "event": event, **context,
        **{name: value for name, (value, _) in values.items()},
    }), flush=True)
