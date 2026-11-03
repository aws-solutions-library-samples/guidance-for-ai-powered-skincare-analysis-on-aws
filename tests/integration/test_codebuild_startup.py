"""Exercise the real build script with no real cloud executables on PATH."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
STUB = r'''
import json, os, sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps({"name": name, "args": args}) + "\n")
if name == "sleep":
    sys.exit(0)
scenario = os.environ["SCENARIO"]
state = Path(os.environ["STATE_FILE"])
attempt = int(state.read_text()) if state.exists() else 0
if args[:2] == ["ecr", "describe-images"]:
    if "imageDetails[0].imageDigest" in args:
        print("sha256:cached" if scenario == "existing" else "None")
    else:
        print("1024")
elif args[:2] == ["codebuild", "start-build"]:
    state.write_text(str(attempt + 1))
    print("test-build:" + str(attempt + 1))
elif args[:2] == ["codebuild", "batch-get-builds"]:
    if "builds[0].phases" in args:
        message = ("is not authorized to perform: logs:CreateLogStream "
                   "because no identity-based policy allows the logs:CreateLogStream action")
        if scenario == "explicit_deny":
            message = "logs:CreateLogStream with an explicit deny in a session policy"
        if scenario == "unrelated":
            message = "s3:GetObject because no identity-based policy allows the s3:GetObject action"
        phases = [
            {"phaseType": "SUBMITTED", "phaseStatus": "SUCCEEDED"},
            {"phaseType": "QUEUED", "phaseStatus": "CLIENT_ERROR",
             "contexts": [{"statusCode": "ACCESS_DENIED", "message": message}]},
            {"phaseType": "COMPLETED"},
        ]
        if scenario == "after_execution":
            phases.insert(2, {"phaseType": "BUILD", "phaseStatus": "FAILED"})
        print(json.dumps(phases))
    else:
        success = scenario == "transient" and attempt > 1
        print(("SUCCEEDED" if success else "FAILED") + "\tCOMPLETED")
else:
    raise RuntimeError("Unexpected AWS command: " + repr(args))
'''


def run_build(tmp_path, scenario):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("aws", "sleep"):
        executable = bin_dir / name
        executable.write_text(f"#!{sys.executable}\n{STUB}")
        executable.chmod(0o755)
    (bin_dir / "python3").symlink_to(sys.executable)
    (bin_dir / "awk").symlink_to(shutil.which("awk"))
    log = tmp_path / "calls.jsonl"
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "terraform/scripts/build-image.sh"),
         "test-project", "us-east-1", "test-repo", "test-tag", "test-repository"],
        env={
            "PATH": str(bin_dir), "SCENARIO": scenario,
            "STATE_FILE": str(tmp_path / "attempts"), "CALL_LOG": str(log),
        },
        text=True, capture_output=True, timeout=10,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    starts = [call for call in calls if call["args"][:2] == ["codebuild", "start-build"]]
    sleeps = [int(call["args"][0]) for call in calls if call["name"] == "sleep"]
    return result, starts, sleeps


def test_new_role_log_permission_delay_retries_then_verifies_image(tmp_path):
    result, starts, sleeps = run_build(tmp_path, "transient")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(starts) == 2
    assert sleeps == [10]
    assert "Image verified:" in result.stdout


@pytest.mark.parametrize("scenario", ["explicit_deny", "unrelated", "after_execution"])
def test_other_build_failures_are_not_retried(tmp_path, scenario):
    result, starts, sleeps = run_build(tmp_path, scenario)
    assert result.returncode != 0
    assert len(starts) == 1
    assert sleeps == []


def test_persistent_startup_denial_has_a_finite_retry_budget(tmp_path):
    result, starts, sleeps = run_build(tmp_path, "persistent")
    assert result.returncode != 0
    assert len(starts) == 4
    assert sleeps == [10, 20, 40]


def test_existing_immutable_image_skips_codebuild(tmp_path):
    result, starts, sleeps = run_build(tmp_path, "existing")
    assert result.returncode == 0
    assert starts == sleeps == []
