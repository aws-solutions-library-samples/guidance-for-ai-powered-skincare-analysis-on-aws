"""Qualification must reject stale evidence before acquiring an AWS session."""

import json
import zipfile

import pytest

from tests import aws_search_qualification as qualification


@pytest.fixture
def worker_project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    files = {
        "agents/__init__.py": "agents/__init__.py",
        "agents/telemetry.py": "agents/telemetry.py",
        "agents/search/clients.py": "agents/search/clients.py",
        "handler.py": "catalog_worker/handler.py",
        "data/search-config.json": "data/search-config.json",
        "data/ingredient-registry.json": "data/ingredient-registry.json",
    }
    archive_path = root / "catalog_worker/.build/function.zip"
    archive_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for member, relative in files.items():
            content = (qualification.ROOT / relative).read_bytes()
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            archive.writestr(member, content)
    monkeypatch.setattr(qualification, "ROOT", root)
    monkeypatch.setattr(
        qualification, "session",
        lambda *args: pytest.fail("A stale artifact reached the AWS session boundary"),
    )
    return root, archive_path


@pytest.mark.parametrize("change", ["modified_source", "deleted_source", "duplicate_member"])
def test_prepare_rejects_stale_worker_before_cloud_access(worker_project, tmp_path, change):
    root, archive_path = worker_project
    client = root / "agents/search/clients.py"
    if change == "modified_source":
        client.write_text(client.read_text().replace(
            "ssl_assert_hostname=parsed.hostname", "ssl_assert_hostname=True",
        ))
    elif change == "deleted_source":
        client.unlink()
    else:
        with zipfile.ZipFile(archive_path, "a") as archive:
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("agents/search/clients.py", b"obsolete client")

    with pytest.raises(ValueError, match="worker archive"):
        qualification.prepare(tmp_path / "run", profile="test-profile", account="123456789012")
    assert not (tmp_path / "run").exists()


def test_execute_rejects_missing_provenance_before_cloud_access(tmp_path, monkeypatch):
    (tmp_path / "report.json").write_text(json.dumps({
        "status": "planned", "account": "123456789012", "profile": "test-profile",
        "usd_reserved": 50,
    }))
    monkeypatch.setattr(
        qualification, "session",
        lambda *args: pytest.fail("An unverified plan reached the AWS session boundary"),
    )
    with pytest.raises(ValueError, match="provenance"):
        qualification.execute(tmp_path, profile="test-profile", account="123456789012")


@pytest.mark.parametrize("change", [
    "source", "archive", "saved_plan", "new_terraform_file", "missing_file", None,
])
def test_execute_checks_frozen_inputs_before_cloud_access(tmp_path, monkeypatch, change):
    root, directory = tmp_path / "source", tmp_path / "run"
    root.mkdir()
    directory.mkdir()
    for relative in qualification.source_fingerprints(qualification.ROOT):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((qualification.ROOT / relative).read_bytes())
    # Small opaque archives/plans suffice here: this exercises integrity between
    # preparation and execution, after the separate archive/source check.
    for relative in (
        ".dockerignore", "Dockerfile.agentcore", "agentcore_entrypoint.py", "catalog.py",
        "config.py", "pyproject.toml", "uv.lock", "probe.zip", "plan.json",
        "catalog_worker/handler.py", "catalog_worker/.build/function.zip",
        "api_proxy/.build/function.zip",
        "terraform/main.tf", "terraform/qualification.tfplan", "terraform/prerequisite.tfplan",
    ):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"prepared input")
    monkeypatch.setattr(qualification, "ROOT", root)
    report = {
        "status": "planned", "account": "123456789012", "profile": "test-profile",
        "usd_reserved": 50, "provenance": {
            "version": 1, "source_sha256": qualification.source_fingerprints(root),
            "artifact_sha256": qualification.artifact_fingerprints(directory),
        },
    }
    (directory / "report.json").write_text(json.dumps(report))
    if change == "source":
        (root / "agents/search/clients.py").write_bytes(b"changed code")
    elif change == "archive":
        (directory / "probe.zip").write_bytes(b"changed archive")
    elif change == "saved_plan":
        (directory / "terraform/prerequisite.tfplan").write_bytes(b"changed plan")
    elif change == "new_terraform_file":
        (directory / "terraform/extra.tf").write_bytes(b"additional resource")
    elif change == "missing_file":
        (directory / "terraform/main.tf").unlink()

    calls = []
    def session_boundary(*args):
        calls.append(args)
        raise RuntimeError("Verified inputs reached session boundary")
    monkeypatch.setattr(qualification, "session", session_boundary)
    with pytest.raises(ValueError if change else RuntimeError, match="provenance" if change else "Verified inputs"):
        qualification.execute(directory, profile="test-profile", account="123456789012")
    assert calls == ([] if change else [("test-profile", "123456789012")])
