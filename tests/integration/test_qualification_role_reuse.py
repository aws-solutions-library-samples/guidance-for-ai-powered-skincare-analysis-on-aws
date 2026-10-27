"""Retained test roles cannot be confused with arbitrary or replaced IAM roles."""

import json
from types import SimpleNamespace

import pytest

from tests import aws_search_qualification as qualification


ACCOUNT = "123456789012"
PROFILE = "qualification-test"
PREFIX = "sbq-0123456789ab"


@pytest.fixture
def predecessor(tmp_path):
    directory = tmp_path / "failed"
    (directory / "terraform").mkdir(parents=True)
    (directory / "report.json").write_text(json.dumps({
        "status": "failed", "finished_at": 123, "cleanup_verified": False,
        "account": ACCOUNT, "profile": PROFILE, "region": qualification.REGION,
        "prefix": PREFIX,
    }))
    resources = []
    changes = []
    for index, (kind, name, key, role_name) in enumerate([
        *[("aws_iam_role", "catalog", role, f"{PREFIX}-catalog-{role}")
          for role in ("admin", "worker", "maintenance")],
        ("aws_iam_role", "qualification_reader", None, f"{PREFIX}-reader-probe"),
        ("aws_iam_service_linked_role", "qualification_opensearch", None, qualification.SERVICE_ROLE),
    ]):
        path = "aws-service-role/opensearchservice.amazonaws.com/" if role_name == qualification.SERVICE_ROLE else ""
        instance = {"attributes": {
            "name": role_name, "arn": f"arn:aws:iam::{ACCOUNT}:role/{path}{role_name}",
            "unique_id": f"AROAEXAMPLE{index}",
        }}
        if key is not None:
            instance["index_key"] = key
        resources.append({"mode": "managed", "type": kind, "name": name, "instances": [instance]})
        changes.append({
            "mode": "managed", "address": f"{kind}.{name}" + (f'["{key}"]' if key else ""),
            "change": {"actions": ["create"]},
        })
    (directory / "terraform/terraform.tfstate").write_text(json.dumps({"resources": resources}))
    (directory / "plan.json").write_text(json.dumps({"resource_changes": changes}))
    return directory


def load(directory):
    return qualification.load_role_reuse(directory, profile=PROFILE, account=ACCOUNT)


def iam_for(reuse):
    roles = {}
    for expected in reuse["roles"].values():
        name = expected["name"]
        principal = "opensearchservice.amazonaws.com" if name == qualification.SERVICE_ROLE else "lambda.amazonaws.com"
        roles[name] = {
            "RoleId": expected["role_id"], "Arn": expected["arn"],
            "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"Service": principal}, "Action": "sts:AssumeRole",
            }]},
        }
    inline = {name: {"PolicyNames": []} for name in roles}
    attached = {name: {"AttachedPolicies": (
        [{"PolicyArn": qualification.SERVICE_POLICY}] if name == qualification.SERVICE_ROLE else []
    )} for name in roles}
    return SimpleNamespace(
        roles=roles, inline=inline, attached=attached,
        get_role=lambda RoleName: {"Role": roles[RoleName]},
        list_role_policies=lambda RoleName: inline[RoleName],
        list_attached_role_policies=lambda RoleName: attached[RoleName],
    )


@pytest.mark.parametrize("field,value", [
    ("status", "applying"), ("finished_at", None), ("cleanup_verified", True),
    ("account", "999999999999"), ("profile", "other"), ("region", "us-east-1"),
    ("prefix", "production"),
])
def test_reuse_rejects_wrong_or_unfinished_predecessor(predecessor, field, value):
    path = predecessor / "report.json"
    report = json.loads(path.read_text())
    report[field] = value
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="terminal failed"):
        load(predecessor)


@pytest.mark.parametrize("change", ["missing_role", "foreign_role", "missing_id", "billable_resource", "not_created"])
def test_reuse_requires_original_creation_and_exact_retained_state(predecessor, change):
    path = predecessor / "terraform/terraform.tfstate"
    state = json.loads(path.read_text())
    if change == "missing_role":
        state["resources"].pop()
    elif change == "foreign_role":
        state["resources"][0]["instances"][0]["attributes"]["arn"] = "arn:aws:iam::999999999999:role/foreign"
    elif change == "missing_id":
        del state["resources"][0]["instances"][0]["attributes"]["unique_id"]
    elif change == "billable_resource":
        state["resources"].append({
            "mode": "managed", "type": "aws_opensearch_domain", "name": "products",
            "instances": [{"attributes": {"id": "still-running"}}],
        })
    else:
        (predecessor / "plan.json").write_text('{"resource_changes": []}')
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="Role reuse"):
        load(predecessor)


@pytest.mark.parametrize("change", [
    "replaced_id", "foreign_arn", "trust", "boundary", "inline", "attached",
    "truncated_inline", "truncated_attached", "missing_service_policy", None,
])
def test_live_role_verification_fails_closed(predecessor, change):
    reuse = load(predecessor)
    iam = iam_for(reuse)
    name = f"{PREFIX}-catalog-admin"
    if change == "replaced_id":
        iam.roles[name]["RoleId"] = "AROA_REPLACEMENT_SAME_NAME"
    elif change == "foreign_arn":
        iam.roles[name]["Arn"] += "-different"
    elif change == "trust":
        iam.roles[name]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"] = {"AWS": "*"}
    elif change == "boundary":
        iam.roles[name]["PermissionsBoundary"] = {"PermissionsBoundaryArn": "unexpected"}
    elif change == "inline":
        iam.inline[name]["PolicyNames"] = ["foreign-policy"]
    elif change == "attached":
        iam.attached[name]["AttachedPolicies"] = [{"PolicyArn": "unexpected"}]
    elif change == "truncated_inline":
        iam.inline[name]["IsTruncated"] = True
    elif change == "truncated_attached":
        iam.attached[name]["IsTruncated"] = True
    elif change == "missing_service_policy":
        iam.attached[qualification.SERVICE_ROLE]["AttachedPolicies"] = []
    aws = SimpleNamespace(client=lambda *args, **kwargs: iam)
    if change:
        with pytest.raises(ValueError, match="identity, trust or permissions"):
            qualification.verify_reused_roles(reuse, aws)
    else:
        qualification.verify_reused_roles(reuse, aws)
    assert json.loads((predecessor / "report.json").read_text())["status"] == "failed"


def test_changed_parent_state_is_rejected_before_iam_access(predecessor):
    reuse = load(predecessor)
    (predecessor / "terraform/terraform.tfstate").write_text("{}")
    aws = SimpleNamespace(client=lambda *args, **kwargs: pytest.fail("Changed ownership reached AWS"))
    with pytest.raises(ValueError, match="predecessor changed"):
        qualification.verify_reused_roles(reuse, aws)


@pytest.mark.parametrize("change", ["create_role", "delete_role", "different_id", "missing_role", None])
def test_reuse_plan_cannot_manage_roles_or_change_identity(predecessor, change):
    reuse = load(predecessor)
    resources = [{
        "mode": "data", "type": "aws_iam_role",
        "values": {"name": role["name"], "arn": role["arn"], "unique_id": role["role_id"]},
    } for role in reuse["roles"].values()]
    planned = {"resource_changes": [], "planned_values": {"root_module": {"resources": resources}}}
    if change in ("create_role", "delete_role"):
        planned["resource_changes"].append({
            "mode": "managed", "type": "aws_iam_role", "change": {"actions": [change.split("_")[0]]},
        })
    elif change == "different_id":
        resources[0]["values"]["unique_id"] = "replacement"
    elif change == "missing_role":
        resources.pop()
    if change:
        with pytest.raises(ValueError, match="roles"):
            qualification.validate_reuse_plan(planned, reuse)
    else:
        qualification.validate_reuse_plan(planned, reuse)


@pytest.mark.parametrize("conflict", [False, True])
def test_reuse_plan_reads_refreshed_data_from_prior_state(predecessor, conflict):
    reuse = load(predecessor)
    resources = [{
        "mode": "data", "type": "aws_iam_role",
        "values": {"name": role["name"], "arn": role["arn"], "unique_id": role["role_id"]},
    } for role in reuse["roles"].values()]
    planned = {
        "resource_changes": [],
        "prior_state": {"values": {"root_module": {"resources": resources}}},
        "planned_values": {"root_module": {"resources": []}},
    }
    if conflict:
        changed = json.loads(json.dumps(resources[0]))
        changed["values"]["unique_id"] = "replacement"
        planned["planned_values"]["root_module"]["resources"] = [changed]
        with pytest.raises(ValueError, match="roles disagree"):
            qualification.validate_reuse_plan(planned, reuse)
    else:
        qualification.validate_reuse_plan(planned, reuse)


def test_role_reuse_template_preserves_original_workspace(tmp_path):
    tf = tmp_path / "terraform"
    tf.mkdir()
    source = qualification.ROOT / "terraform/search.tf"
    original = source.read_bytes()
    (tf / "search.tf").write_bytes(original)
    (tf / "qualification.tf").write_text('''
resource "aws_iam_service_linked_role" "qualification_opensearch" {
  aws_service_name = "opensearchservice.amazonaws.com"
}
resource "aws_iam_role" "qualification_reader" {
  name = "${local.prefix}-reader-probe"
  assume_role_policy = data.aws_iam_policy_document.api_proxy_assume.json
}
''')
    qualification.configure_role_reuse(tf)
    assert source.read_bytes() == original
    changed = (tf / "search.tf").read_text()
    assert 'resource "aws_iam_role" "catalog"' not in changed
    assert 'data "aws_iam_role" "reused_catalog"' in changed
    assert 'role     = data.aws_iam_role.reused_catalog[each.key].id' in changed
    assert 'resource "aws_iam_role"' not in (tf / "qualification.tf").read_text()


@pytest.mark.parametrize("change", ["tail_id", "tail_count", "truncated", "missing_count", "wrong_status", None])
def test_managed_oracle_rejects_wrong_tail_even_with_correct_top_three(change):
    wanted = [(f"product-{index:03}", 1) for index in range(100)]
    actual = {
        "candidate_ids": [item[0] for item in wanted], "candidate_counts": [1] * 100,
        "ids": [item[0] for item in wanted[:3]], "counts": [1] * 3, "status": "matched",
    }
    if change == "tail_id":
        actual["candidate_ids"][-1] = "wrong-product"
    elif change == "tail_count":
        actual["candidate_counts"][-1] = 2
    elif change == "truncated":
        actual["candidate_ids"].pop()
        actual["candidate_counts"].pop()
    elif change == "missing_count":
        actual["candidate_counts"].pop()
    elif change == "wrong_status":
        actual["status"] = "no_match"
    if change:
        with pytest.raises((AssertionError, ValueError)):
            qualification.verify_oracle_results([actual], [wanted])
    else:
        qualification.verify_oracle_results([actual], [wanted])
