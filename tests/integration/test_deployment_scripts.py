"""Run copied deployment scripts against command stubs in a temporary project.

No real AWS, Terraform, npm, or uv executable is reachable from these scripts.
The stubs record argv/environment and model failures at deployment boundaries.
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]

STUB = r'''
import json, os, sys
from pathlib import Path
command = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps({"command": command, "args": args, "cwd": os.getcwd(),
        "region": os.environ.get("AWS_REGION"),
        "default_region": os.environ.get("AWS_DEFAULT_REGION")}) + "\n")
if command == "aws":
    if args[:3] == ["configure", "get", "region"]:
        print(os.environ.get("PROFILE_REGION", "eu-west-1"))
    elif args[:2] == ["sts", "get-caller-identity"]:
        print("123456789012")
    elif args[:2] == ["apigateway", "get-account"]:
        if os.environ.get("FAIL_LOGGING_LOOKUP"): sys.exit(6)
        print(os.environ.get("EXISTING_LOGGING_ROLE", "None"))
elif command == "terraform":
    if args[0] == "apply" and os.environ.get("FAIL_APPLY"): sys.exit(8)
    if args[0] == "output":
        print({"app_url":"https://example.invalid", "api_url":"https://example.invalid/api",
            "frontend_bucket":"test-bucket", "products_table_name":"test-products",
            "catalog_metadata_table_name":"test-metadata", "catalog_outbox_table_name":"test-outbox",
            "catalog_admin_function_name":"test-admin",
            "aws_region":"eu-west-1"}.get(args[-1], "test-value"))
elif command == "npm" and args == ["run", "typecheck"] and os.environ.get("FAIL_TYPES"):
    sys.exit(9)
elif command == "uv" and "scripts/migrate_products.py" in args and os.environ.get("FAIL_PUBLISH"):
    sys.exit(7)
'''


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "project"
    for directory in ("scripts", "terraform/shared", "frontend", "api_proxy"):
        (project / directory).mkdir(parents=True)
    for script in ("deploy.sh", "destroy.sh"):
        shutil.copy2(ROOT / "scripts" / script, project / "scripts" / script)
    shutil.copy2(ROOT / "Makefile", project / "Makefile")
    (project / "terraform" / "env-prod.tfvars").write_text('environment = "prod"\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("aws", "terraform", "node", "npm", "uv"):
        stub = bin_dir / command
        stub.write_text(f"#!{sys.executable}\n{STUB}")
        stub.chmod(0o755)
    # Shell scripts need dirname; do not include the caller's PATH/cloud tools.
    (bin_dir / "dirname").symlink_to(shutil.which("dirname"))
    env = {
        "PATH": str(bin_dir),
        "COMMAND_LOG": str(tmp_path / "commands.jsonl"),
        "PROFILE_REGION": "eu-west-1",
    }
    return project, env


def run_script(project, name, *args, input=""):
    directory, env = project
    result = subprocess.run(
        ["/bin/bash", str(directory / "scripts" / name), *args],
        cwd=directory, env=env, input=input, text=True, capture_output=True, timeout=10,
    )
    log = Path(env["COMMAND_LOG"])
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


@pytest.mark.parametrize("env_vars,region", [
    ({"AWS_REGION": "eu-central-1", "AWS_DEFAULT_REGION": "ap-south-1"}, "eu-central-1"),
    ({"AWS_DEFAULT_REGION": "ap-south-1"}, "ap-south-1"),
    ({}, "eu-west-1"),
    ({"PROFILE_REGION": ""}, "us-east-1"),
])
def test_deploy_uses_one_region_for_infrastructure_and_migration(project, env_vars, region):
    project[1].update(env_vars)
    result, calls = run_script(project, "deploy.sh", "prod")
    assert result.returncode == 0, result.stdout + result.stderr
    applies = [call for call in calls if call["command"] == "terraform" and call["args"][0] == "apply"]
    assert len(applies) == 2
    assert all(f"-var=aws_region={region}" in call["args"] for call in applies)
    assert "-var=environment=prod" in applies[-1]["args"]
    assert "-var-file=env-prod.tfvars" in applies[-1]["args"]
    migration = next(call for call in calls if call["command"] == "uv" and "scripts/migrate_products.py" in call["args"])
    assert migration["region"] == migration["default_region"] == region
    assert not any(call["command"] == "aws" and call["args"][:2] == ["dynamodb", "scan"] for call in calls)
    assert "--demo-if-empty" in migration["args"] and "--wait-ready" in migration["args"]
    for flag, value in (("--metadata-table", "test-metadata"), ("--outbox-table", "test-outbox"), ("--admin-function", "test-admin")):
        assert migration["args"][migration["args"].index(flag) + 1] == value
    npm_calls = [call["args"] for call in calls if call["command"] == "npm"]
    assert npm_calls == [["ci", "--omit=dev"], ["run", "build"], ["ci"], ["run", "build"]]


@pytest.mark.parametrize("failure", ["FAIL_PUBLISH", "FAIL_APPLY"])
def test_deploy_does_not_continue_after_cloud_failure(project, failure):
    project[1][failure] = "1"
    result, calls = run_script(project, "deploy.sh", "dev")
    assert result.returncode != 0
    if failure == "FAIL_APPLY":
        assert not any("scripts/migrate_products.py" in call["args"] for call in calls)
    assert not any(call["command"] == "npm" and call["cwd"].endswith("/frontend") for call in calls)
    assert not any(call["command"] == "aws" and call["args"][:2] == ["s3", "sync"] for call in calls)


def test_destroy_cancellation_does_not_call_cloud_tools(project):
    result, calls = run_script(project, "destroy.sh", "prod", input="no\n")
    assert result.returncode == 0
    assert "prod" in result.stdout
    assert calls == []


@pytest.mark.parametrize("environment", ["prod", "test"])
def test_destroy_passes_environment_backend_and_region(project, environment):
    project[1]["AWS_REGION"] = "eu-central-1"
    result, calls = run_script(project, "destroy.sh", environment, input="yes\n")
    assert result.returncode == 0, result.stderr
    init = next(call for call in calls if call["command"] == "terraform" and call["args"][0] == "init")
    destroy = next(call for call in calls if call["command"] == "terraform" and call["args"][0] == "destroy")
    assert f"-backend-config=key={environment}/terraform.tfstate" in init["args"]
    assert f"-var=environment={environment}" in destroy["args"]
    assert "-var=aws_region=eu-central-1" in destroy["args"]


def test_test_deployment_uses_its_own_state_and_environment(project):
    result, calls = run_script(project, "deploy.sh", "test")
    assert result.returncode == 0, result.stdout + result.stderr
    inits = [call for call in calls if call["command"] == "terraform" and call["args"][0] == "init"]
    assert "-backend-config=key=test/terraform.tfstate" in inits[-1]["args"]
    applies = [call for call in calls if call["command"] == "terraform" and call["args"][0] == "apply"]
    assert "-var=environment=test" in applies[-1]["args"]


def test_deploy_preserves_existing_account_logging(project):
    project[1]["EXISTING_LOGGING_ROLE"] = "arn:aws:iam::123456789012:role/another-application"
    result, calls = run_script(project, "deploy.sh", "test")
    assert result.returncode == 0, result.stdout + result.stderr
    applies = [c for c in calls if c["command"] == "terraform" and c["args"][0] == "apply"]
    assert len(applies) == 1
    assert not any(c["command"] == "terraform" and c["cwd"].endswith("/shared") for c in calls)
    assert "-var=environment=test" in applies[0]["args"]


def test_deploy_stops_if_account_logging_cannot_be_inspected(project):
    project[1]["FAIL_LOGGING_LOOKUP"] = "1"
    result, calls = run_script(project, "deploy.sh", "test")
    assert result.returncode != 0
    assert not any(c["command"] == "terraform" and c["args"][0] == "apply" for c in calls)


@pytest.mark.parametrize("script,operation", [("deploy.sh", "apply"), ("destroy.sh", "destroy")])
def test_local_overrides_follow_environment_defaults_but_cannot_change_target(project, script, operation):
    directory, _ = project
    (directory / "terraform" / "terraform.tfvars").write_text('custom_domain = "local.example.com"\n')
    result, calls = run_script(project, script, "prod", input="yes\n")
    assert result.returncode == 0, result.stderr
    args = [c["args"] for c in calls if c["command"] == "terraform" and c["args"][0] == operation][-1]
    assert args.index("-var-file=env-prod.tfvars") < args.index("-var-file=terraform.tfvars")
    assert args.index("-var-file=terraform.tfvars") < args.index("-var=environment=prod")
    assert args.index("-var-file=terraform.tfvars") < args.index("-var=aws_region=eu-west-1")


@pytest.mark.parametrize("script", ["deploy.sh", "destroy.sh"])
def test_invalid_environment_fails_before_cloud_calls(project, script):
    result, calls = run_script(project, script, "production")
    assert result.returncode != 0
    assert calls == []


def test_make_destroy_forwards_requested_environment(project):
    directory, env = project
    script = directory / "scripts" / "destroy.sh"
    script.write_text('#!/bin/bash\n[[ "$1" == "prod" ]]\n')
    result = subprocess.run(
        [shutil.which("make"), "destroy", "ENV=prod"], cwd=directory, env=env,
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("target", [[], ["setup"]])
def test_make_default_and_local_setup_never_call_aws(project, target):
    directory, env = project
    result = subprocess.run(
        [shutil.which("make"), *target], cwd=directory, env=env,
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log = Path(env["COMMAND_LOG"])
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert not any(call["command"] in ("aws", "terraform") for call in calls)
    if not target:
        assert calls == []
        assert "make setup" in result.stdout


def test_make_validate_propagates_type_errors(project):
    directory, env = project
    env["FAIL_TYPES"] = "1"
    result = subprocess.run(
        [shutil.which("make"), "validate"], cwd=directory, env=env,
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert "Validation complete" not in result.stdout


def test_create_user_uses_deployed_region_and_generated_email_credentials(project):
    directory, env = project
    result = subprocess.run(
        [shutil.which("make"), "create-user", "EMAIL=example@example.invalid"],
        cwd=directory, env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in Path(env["COMMAND_LOG"]).read_text().splitlines()]
    request = next(call for call in calls if call["command"] == "aws")
    assert request["args"][:2] == ["cognito-idp", "admin-create-user"]
    assert request["args"][request["args"].index("--region") + 1] == "eu-west-1"
    assert request["args"][request["args"].index("--desired-delivery-mediums") + 1] == "EMAIL"
    assert "--temporary-password" not in request["args"]


def test_packaging_includes_selected_files_and_removes_deleted_archive_entries(tmp_path):
    project = tmp_path / "package-project"
    scripts = project / "terraform" / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "package-agent-code.sh"
    shutil.copy2(ROOT / "terraform" / "scripts" / script.name, script)
    (project / "catalog.py").write_text("catalog = 'current'\n")
    (project / "retired.py").write_text("retired = True\n")
    for selected, expected in [
        (["catalog.py", "retired.py"], {"catalog.py", "retired.py"}),
        (["catalog.py"], {"catalog.py"}),
    ]:
        completed = subprocess.run(
            ["/bin/bash", str(script), *selected], cwd=project,
            text=True, capture_output=True, timeout=10,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        with zipfile.ZipFile(project / "terraform" / ".build" / "agent-code.zip") as archive:
            assert set(archive.namelist()) == expected
            assert archive.read("catalog.py") == b"catalog = 'current'\n"


def test_packaging_is_readable_by_container_user_with_restrictive_umask(tmp_path):
    project = tmp_path / "package-project"
    scripts = project / "terraform" / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "package-agent-code.sh"
    shutil.copy2(ROOT / "terraform" / "scripts" / script.name, script)
    source = project / "agents" / "example.py"
    source.parent.mkdir()
    source.write_text("example = True\n")
    source.chmod(0o600)
    completed = subprocess.run(
        ["/bin/bash", str(script), "agents/example.py"], cwd=project,
        text=True, capture_output=True, timeout=10, umask=0o077,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    with zipfile.ZipFile(project / "terraform" / ".build" / "agent-code.zip") as archive:
        assert (archive.getinfo("agents/").external_attr >> 16) & 0o777 == 0o755
        assert (archive.getinfo("agents/example.py").external_attr >> 16) & 0o777 == 0o644
    assert source.stat().st_mode & 0o777 == 0o600
