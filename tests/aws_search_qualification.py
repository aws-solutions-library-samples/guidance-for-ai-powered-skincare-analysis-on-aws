"""Bounded, disposable AWS component qualification; never deploys the full app.

prepare makes a local Terraform copy and saved plan. execute applies that plan,
runs the managed catalog checks, and destroys only the resources in its own
state in a finally block. No model calls, production state or existing resources.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import zipfile

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.search.publication import CatalogPublisher, ControlStore, source_watermarks, shard_key
from tests.search_fixtures import product

REGION = "eu-west-1"
RESERVED_USD = 50


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker_sources(root):
    files = {
        "agents/__init__.py": root / "agents/__init__.py",
        "agents/telemetry.py": root / "agents/telemetry.py",
        "handler.py": root / "catalog_worker/handler.py",
        **{f"data/{name}": root / "data" / name for name in (
            "search-config.json", "ingredient-registry.json",
        )},
    }
    files.update({
        path.relative_to(root).as_posix(): path
        for path in (root / "agents/search").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    })
    return files


def validate_worker_archive(root):
    """Check the deployed application bytes, including removed and duplicate files."""
    sources = worker_sources(root)
    with zipfile.ZipFile(root / "catalog_worker/.build/function.zip") as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("Rebuild the worker archive: duplicate archive members")
        application = {
            name for name in names
            if name.startswith(("agents/", "data/")) or name == "handler.py"
        }
        if application != set(sources) or any(
            archive.read(name) != path.read_bytes() for name, path in sources.items()
        ):
            raise ValueError("Rebuild the worker archive: application sources differ")


def fingerprints(root, folders, files):
    paths = [root / name for name in files]
    for folder in folders:
        paths.extend(
            path for path in (root / folder).rglob("*")
            if path.is_file() and not {".terraform", "__pycache__", ".build"}.intersection(path.parts)
            and not path.name.startswith("terraform.tfstate")
        )
    return {path.relative_to(root).as_posix(): file_hash(path) for path in sorted(set(paths))}


def source_fingerprints(root):
    return fingerprints(
        root, ("agents", "prompts", "data", "docs/search-spec"),
        ("catalog_worker/handler.py", "tests/aws_search_qualification.py",
         "tests/aws_search_probe.py", "tests/search_fixtures.py",
         "scripts/build-catalog-worker.py", "catalog.py", "config.py",
         "agentcore_entrypoint.py", "pyproject.toml", "uv.lock"),
    )


def artifact_fingerprints(directory):
    return fingerprints(
        directory, ("agents", "prompts", "data", "terraform", "tests", "spec"),
        (".dockerignore", "Dockerfile.agentcore", "agentcore_entrypoint.py", "catalog.py",
         "config.py", "pyproject.toml", "uv.lock", "probe.zip", "plan.json",
         "catalog_worker/handler.py", "catalog_worker/.build/function.zip",
         "api_proxy/.build/function.zip"),
    )


def verify_provenance(directory, report):
    provenance = report.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("version") != 1:
        raise ValueError("Plan has no verified provenance; prepare a new qualification run")
    if source_fingerprints(ROOT) != provenance.get("source_sha256"):
        raise ValueError("Source provenance changed after preparation; prepare a new run")
    if artifact_fingerprints(directory) != provenance.get("artifact_sha256"):
        raise ValueError("Artifact provenance changed after review; prepare a new run")


def environment(report):
    inherited = {key: value for key, value in os.environ.items() if key not in (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
    )}
    return {**inherited, "AWS_PROFILE": report["profile"], "AWS_REGION": REGION, "AWS_DEFAULT_REGION": REGION}


def terraform(folder, arguments, log, *, timeout=1800):
    report = json.loads((log.parent / "report.json").read_text())
    with log.open("w") as output:
        subprocess.run(["terraform", *arguments], cwd=folder, env=environment(report),
                       stdout=output, stderr=subprocess.STDOUT, timeout=timeout, check=True)


def session(profile, account):
    if not re.fullmatch(r"\d{12}", account):
        raise ValueError("An explicit 12-digit AWS account is required")
    result = boto3.Session(profile_name=profile, region_name=REGION)
    if result.client("sts").get_caller_identity()["Account"] != account:
        raise ValueError("Qualification account differs from the user's approved account")
    return result


def prepare(directory, *, profile, account):
    validate_worker_archive(ROOT)
    source_sha256 = source_fingerprints(ROOT)
    session(profile, account)
    directory.mkdir(parents=True, exist_ok=False)
    tf = directory / "terraform"
    shutil.copytree(ROOT / "terraform", tf, ignore=shutil.ignore_patterns(
        ".terraform", "*.tfstate*", "*.tfvars", "backend.hcl", ".build", "shared",
    ))
    # Source, assets and locked deployment archives are copied, never linked
    # to a mutable deployment workspace.
    for name in ("agents", "prompts", "data"):
        shutil.copytree(ROOT / name, directory / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in (".dockerignore", "Dockerfile.agentcore", "agentcore_entrypoint.py",
                 "catalog.py", "config.py", "pyproject.toml", "uv.lock"):
        shutil.copyfile(ROOT / name, directory / name)
    shutil.copytree(ROOT / "docs/search-spec", directory / "spec")
    (directory / "tests").mkdir()
    for name in ("aws_search_qualification.py", "aws_search_probe.py", "search_fixtures.py"):
        shutil.copyfile(ROOT / "tests" / name, directory / "tests" / name)
    for name in ("catalog_worker", "api_proxy"):
        target = directory / name / ".build"
        target.mkdir(parents=True)
        shutil.copyfile(ROOT / name / ".build/function.zip", target / "function.zip")
    shutil.copyfile(ROOT / "catalog_worker/handler.py", directory / "catalog_worker/handler.py")
    validate_worker_archive(directory)
    probe = directory / "probe.zip"
    shutil.copyfile(directory / "catalog_worker/.build/function.zip", probe)
    with zipfile.ZipFile(probe, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("qualification_probe.py", (ROOT / "tests/aws_search_probe.py").read_bytes())
    prefix = "sbq-" + uuid4().hex[:12]
    versions = tf / "versions.tf"
    versions.write_text(versions.read_text().replace('backend "s3" {}', 'backend "local" {}').replace(
        'provider "aws" {', f'provider "aws" {{\n  allowed_account_ids = ["{account}"]',
    ))
    main = tf / "main.tf"
    main.write_text(main.read_text().replace('"smart-beauty-${var.environment}"', json.dumps(prefix)))
    # A private Lambda exercises the exact runtime search/read policy fragment.
    # Its service principal differs from AgentCore, so this does not qualify
    # AgentCore networking, trust policy, SSE, models or end-to-end capacity.
    original_iam = (ROOT / "terraform/iam.tf").read_text()
    read_statements = original_iam.split("  # Runtime has no product scan/query or publication permissions.")[1].split("  # CloudWatch Logs")[0]
    search = tf / "search.tf"
    search.write_text(search.read_text().replace(
        "Principal = { AWS = aws_iam_role.agentcore_execution.arn }",
        "Principal = { AWS = [aws_iam_role.agentcore_execution.arn, aws_iam_role.qualification_reader.arn] }",
    ).replace(
        "SEARCH_RUNTIME_ROLE_ARN     = aws_iam_role.agentcore_execution.arn",
        "SEARCH_RUNTIME_ROLE_ARN     = aws_iam_role.qualification_reader.arn",
    ).replace(
        'resource "aws_opensearch_domain" "products" {',
        'resource "aws_opensearch_domain" "products" {\n  depends_on = [aws_iam_service_linked_role.qualification_opensearch]',
    ).replace(
        'schedule_expression = "rate(1 minute)"',
        'schedule_expression = "rate(1 minute)"\n  state = "DISABLED"',
    ))
    extra = '''
resource "aws_iam_service_linked_role" "qualification_opensearch" {
  aws_service_name = "opensearchservice.amazonaws.com"
}
resource "aws_iam_role" "qualification_reader" {
  name = "${local.prefix}-reader-probe"
  assume_role_policy = data.aws_iam_policy_document.api_proxy_assume.json
}
data "aws_iam_policy_document" "qualification_reader" {
__READ_STATEMENTS__
  statement {
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.qualification_reader.arn}:*"]
  }
  statement {
    actions = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets", "ec2:DeleteNetworkInterface", "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses"]
    resources = ["*"]
  }
}
resource "aws_iam_role_policy" "qualification_reader" {
  role = aws_iam_role.qualification_reader.id
  policy = data.aws_iam_policy_document.qualification_reader.json
}
resource "aws_cloudwatch_log_group" "qualification_reader" {
  name = "/aws/lambda/${local.prefix}-reader-probe"
  retention_in_days = 1
}
resource "aws_lambda_function" "qualification_probe" {
  for_each = toset(["reader", "writer"])
  function_name = "${local.prefix}-${each.key}-probe"
  role = each.key == "reader" ? aws_iam_role.qualification_reader.arn : aws_iam_role.catalog["worker"].arn
  runtime = "python3.12"
  architectures = ["x86_64"]
  handler = "qualification_probe.handler"
  filename = "${path.module}/../probe.zip"
  source_code_hash = filebase64sha256("${path.module}/../probe.zip")
  timeout = 60
  memory_size = 512
  reserved_concurrent_executions = 1
  logging_config {
    log_format = "Text"
    log_group = each.key == "reader" ? aws_cloudwatch_log_group.qualification_reader.name : aws_cloudwatch_log_group.catalog["worker"].name
  }
  vpc_config {
    subnet_ids = aws_subnet.search[*].id
    security_group_ids = [aws_security_group.search_clients.id]
  }
  environment {
    variables = {
      QUALIFICATION_ROLE = each.key
      PRODUCTS_TABLE_NAME = aws_dynamodb_table.canonical_products.name
      CATALOG_METADATA_TABLE_NAME = aws_dynamodb_table.catalog_metadata.name
      OPENSEARCH_ENDPOINT = "https://${aws_opensearch_domain.products.endpoint}"
    }
  }
  depends_on = [aws_iam_role_policy.qualification_reader, aws_iam_role_policy.catalog, aws_vpc_endpoint.search_apis, aws_vpc_endpoint.search_dynamodb, aws_security_group_rule.search_egress, aws_security_group_rule.search_gateway_egress]
}
'''
    (tf / "qualification.tf").write_text(extra.replace("__READ_STATEMENTS__", read_statements))
    targets = []
    for name in ("search.tf", "search_monitoring.tf", "qualification.tf"):
        targets.extend(f"{kind}.{name}" for kind, name in re.findall(
            r'^resource "([^"]+)" "([^"]+)"', (tf / name).read_text(), re.MULTILINE,
        ))
    report = {
        "status": "prepared", "account": account, "profile": profile, "region": REGION,
        "prefix": prefix, "usd_reserved": RESERVED_USD, "total_qualification_ceiling_usd": 200,
        "created_at": time.time(), "targets": targets,
        "scope": "private managed OpenSearch, native IAM policy fragment, DynamoDB publication/rebuild/rollback; no models or full application",
        "runtime_read_policy_sha256": hashlib.sha256(read_statements.encode()).hexdigest(),
        "budget": {
            "maximum_apply_seconds": 2700, "maximum_test_seconds": 1800, "cleanup_reserved_hours": 24,
            "search_nodes_per_hour_usd": 2 * .187, "endpoint_interfaces_per_hour_usd": 14 * .011,
            "storage_60_gib_month_usd": 60 * .1342,
            "bounded_request_log_lambda_storage_allowance_usd": 20,
            "expected_maximum_usd": 35,
        },
    }
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    # Reuse verified locked providers without making any version changes.
    plugin_directory = ROOT / "terraform/.terraform/providers"
    terraform(tf, ["init", "-input=false", f"-plugin-dir={plugin_directory}"], directory / "init.log")
    terraform(tf, ["plan", "-input=false", "-no-color", "-var=environment=test", "-var=aws_region=eu-west-1",
                   "-out=qualification.tfplan", *[f"-target={target}" for target in targets]], directory / "plan.log")
    planned = subprocess.check_output(["terraform", "show", "-json", "qualification.tfplan"], cwd=tf, env=environment(report))
    (directory / "plan.json").write_bytes(planned)
    changes = [change for change in json.loads(planned)["resource_changes"] if change["mode"] == "managed"]
    assert changes and all(change["change"]["actions"] == ["create"] for change in changes)
    terraform(tf, ["plan", "-input=false", "-no-color", "-var=environment=test", "-var=aws_region=eu-west-1",
                   "-out=prerequisite.tfplan", "-target=aws_iam_service_linked_role.qualification_opensearch"],
              directory / "prerequisite-plan.log")
    if source_fingerprints(ROOT) != source_sha256:
        raise ValueError("Source provenance changed during preparation; prepare a new run")
    report.update(planned_resources=len(changes), status="planned", provenance={
        "version": 1, "source_sha256": source_sha256,
        "artifact_sha256": artifact_fingerprints(directory),
    })
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"directory": str(directory), "prefix": prefix, "planned_resources": len(changes), "usd_reserved": RESERVED_USD}))


def cloud_checks(directory, report, aws):
    prefix = report["prefix"]
    client = aws.client("dynamodb", config=Config(retries={"total_max_attempts": 1}, read_timeout=5))
    control = ControlStore(client, f"{prefix}-CatalogMetadata", "demo")
    publisher = CatalogPublisher(client, products_table=f"{prefix}-ProductsV2",
                                 outbox_table=f"{prefix}-CatalogOutbox", control=control)
    functions = aws.client("lambda", config=Config(retries={"total_max_attempts": 1}, read_timeout=310))
    deadline = time.monotonic() + 1800
    invocations = 0
    invocation_lock = threading.Lock()
    def invoke(kind, event):
        nonlocal invocations
        with invocation_lock:
            if time.monotonic() >= deadline or invocations >= 300:
                raise RuntimeError("Qualification invocation/time budget exhausted")
            invocations += 1
            report["invocations"] = invocations
        name = f"{prefix}-{kind}-probe" if kind in ("reader", "writer") else f"{prefix}-catalog-{kind}"
        response = functions.invoke(FunctionName=name, InvocationType="RequestResponse", Payload=json.dumps(event).encode())
        body = json.loads(response["Payload"].read())
        if response.get("FunctionError"):
            raise RuntimeError(f"{kind} invocation failed: {json.dumps(body)}")
        return body
    assert invoke("admin", {"action": "initialize"})["status"] == "initialized"
    registry = json.loads((directory / "data/ingredient-registry.json").read_text())
    ingredient_ids = [entry["ingredient_id"] for entry in registry][:6]
    assert len(ingredient_ids) >= 3
    rng = random.Random(20261027)
    records = [product(
        f"cloud-{offset:04}", catalog_id="demo", taxonomy_version="demo-v1",
        ingredient_ids=rng.sample(ingredient_ids, rng.randint(1, len(ingredient_ids))),
        category_id="Cleanser" if offset % 2 else "Serum", availability="available",
        price_minor=(offset % 20) * 100, ingredient_list_complete=offset % 7 != 0,
        ingredient_resolution_complete=offset % 9 != 0, active=offset % 17 != 0,
        is_deleted=offset % 19 == 0,
    ) for offset in range(240)]
    corpus = directory / "corpus.json"
    corpus.write_text(json.dumps([record.model_dump(mode="json") for record in records], indent=2) + "\n")
    report["corpus_sha256"] = file_hash(corpus)
    # Serialize publication to avoid making unqualified sustained-update claims.
    assert Counter(publisher.publish(record) for record in records) == {"published": len(records)}
    publisher.set_source_health(True, mode="snapshot")

    def ready(generation, *, rebuilding=False):
        for attempt in range(6):
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(lambda shard: invoke("worker", {"shard": shard}), range(16)))
            invoke("maintenance", {})
            source = source_watermarks(control)
            progress = [control.get(shard_key("PROJECTION", shard))["generations"][generation] for shard in range(16)]
            reconciliation = control.get(f"RECONCILIATION#{generation}")
            if all(item["sequence"] == source[shard] and not item["error"] for shard, item in enumerate(progress)) and (
                reconciliation and reconciliation["status"] == "complete"
            ) and (not rebuilding or control.get("REBUILD")["complete"]):
                return
        raise AssertionError("Publication/backfill/reconciliation did not become ready")
    ready("products-demo-v1")
    cases, expected = [], []
    for offset in range(24):
        preferred = rng.sample(ingredient_ids, 3)
        required = ingredient_ids[:1] if offset % 3 == 0 else []
        excluded = ingredient_ids[-1:] if offset % 4 == 0 else []
        category = "Serum" if offset % 2 else "Cleanser"
        cap = 700 if offset % 5 == 0 else None
        case = {"category_id": category, "preferred_ingredient_ids": preferred,
                "must_have_ingredient_ids": required, "excluded_ingredient_ids": excluded,
                "market": "GB", "currency": "GBP", "max_price_minor": cap}
        matches = []
        for record in records:
            ingredients = set(record.ingredient_ids)
            count = len(set(preferred) & ingredients)
            if (record.active and not record.is_deleted and record.category_id == category
                and count and set(required) <= ingredients and not set(excluded) & ingredients
                and (not excluded or (record.ingredient_list_complete and record.ingredient_resolution_complete))
                and (cap is None or record.price_minor <= cap)):
                matches.append((record.product_id, count))
        expected.append(sorted(matches, key=lambda item: (-item[1], item[0]))[:3])
        cases.append(case)
    def oracle():
        result = invoke("reader", {"requests": cases})
        for actual, wanted in zip(result["results"], expected, strict=True):
            assert list(zip(actual["ids"], actual["counts"])) == wanted
        return result
    report["first_generation"] = oracle()
    report["writer_permissions"] = invoke("writer", {})
    assert invoke("admin", {"action": "start_rebuild", "generation": "products-cloud-v2"})["status"] == "backfill_started"
    ready("products-cloud-v2", rebuilding=True)
    report["cutover"] = invoke("admin", {"action": "activate", "generation": "products-cloud-v2"})
    invoke("maintenance", {})
    report["rebuilt_generation"] = oracle()
    report["rollback"] = invoke("admin", {"action": "activate", "generation": "products-demo-v1"})
    invoke("maintenance", {})
    report["rolled_back_generation"] = oracle()
    report.update(records=240, oracle_cases=72, invocations=invocations, qualification_checks="passed")


def execute(directory, *, profile, account):
    report_file = directory / "report.json"
    report = json.loads(report_file.read_text())
    if (report["status"] != "planned" or report["account"] != account
        or report["profile"] != profile or report["usd_reserved"] != 50):
        raise ValueError("Execute requires this harness's reviewed, unapplied plan")
    verify_provenance(directory, report)
    aws = session(profile, account)
    # This account-wide role was absent at preflight. Do not claim or destroy a
    # role that somebody else creates between the plan and the apply.
    iam = aws.client("iam")
    try:
        iam.get_role(RoleName="AWSServiceRoleForAmazonOpenSearchService")
    except iam.exceptions.NoSuchEntityException:
        pass
    else:
        raise RuntimeError("OpenSearch service role now exists; revise ownership before applying")
    report.update(status="applying", started_at=time.time())
    report_file.write_text(json.dumps(report, indent=2) + "\n")
    try:
        # Match the application's separate shared-role provisioning phase.
        # The first one-graph run failed with AWS's "enable a service-linked role"
        # validation error immediately after IAM creation. Preserve that failed
        # run; allow IAM propagation before testing the separate domain phase.
        terraform(directory / "terraform", ["apply", "-input=false", "-no-color", "prerequisite.tfplan"],
                  directory / "prerequisite-apply.log", timeout=300)
        role = iam.get_role(RoleName="AWSServiceRoleForAmazonOpenSearchService")["Role"]
        policies = iam.list_attached_role_policies(RoleName=role["RoleName"])["AttachedPolicies"]
        assert any(policy["PolicyName"] == "AmazonOpenSearchServiceRolePolicy" for policy in policies)
        report["service_role_verified_at"] = time.time()
        report_file.write_text(json.dumps(report, indent=2) + "\n")
        time.sleep(60)
        # A saved plan is stale after its prerequisite changes the local state.
        # Regenerate against the frozen copy; forbid replacement, update or
        # deletion, and forbid adding resources outside the reviewed plan.
        terraform(directory / "terraform", ["plan", "-input=false", "-no-color", "-var=environment=test",
                  "-var=aws_region=eu-west-1", "-out=execution.tfplan",
                  *[f"-target={target}" for target in report["targets"]]], directory / "execution-plan.log")
        planned = json.loads(subprocess.check_output(
            ["terraform", "show", "-json", "execution.tfplan"], cwd=directory / "terraform", env=environment(report),
        ))
        approved = {change["address"] for change in json.loads((directory / "plan.json").read_text())["resource_changes"]}
        for change in planned["resource_changes"]:
            if change["mode"] == "managed":
                assert change["address"] in approved and change["change"]["actions"] in (["create"], ["no-op"])
        (directory / "execution-plan.json").write_text(json.dumps(planned, indent=2) + "\n")
        report["execution_plan_sha256"] = file_hash(directory / "terraform/execution.tfplan")
        report["execution_plan_json_sha256"] = file_hash(directory / "execution-plan.json")
        report_file.write_text(json.dumps(report, indent=2) + "\n")
        terraform(directory / "terraform", ["apply", "-input=false", "-no-color", "execution.tfplan"],
                  directory / "apply.log", timeout=2700)
        report["status"] = "testing"
        report_file.write_text(json.dumps(report, indent=2) + "\n")
        cloud_checks(directory, report, aws)
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        report["cleanup_started_at"] = time.time()
        report_file.write_text(json.dumps(report, indent=2) + "\n")
        try:
            terraform(directory / "terraform", ["destroy", "-auto-approve", "-input=false", "-no-color",
                      "-var=environment=test", "-var=aws_region=eu-west-1"],
                      directory / "destroy.log", timeout=2700)
            state = json.loads((directory / "terraform/terraform.tfstate").read_text())
            assert not [resource for resource in state.get("resources", []) if resource["mode"] == "managed"]
            report["cleanup_verified"] = True
        except Exception as exc:
            report.update(cleanup_verified=False, cleanup_error=str(exc))
        report["finished_at"] = time.time()
        report_file.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        if not report["cleanup_verified"]:
            raise RuntimeError(f"Cloud resources require cleanup using {directory / 'terraform'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "execute"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    if not args.directory.is_absolute():
        raise ValueError("Use an absolute dedicated qualification directory")
    (prepare if args.action == "prepare" else execute)(args.directory, profile=args.profile, account=args.account)
