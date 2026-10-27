"""Build a deterministic Linux Lambda archive from the application's locked SDKs."""

import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "catalog_worker/.build/function.zip"
lock = tomllib.loads((root / "uv.lock").read_text())
packages = {item["name"]: item for item in lock["package"]}
required = set()


def include(name):
    if name in required:
        return
    required.add(name)
    for dependency in packages[name].get("dependencies", []):
        include(dependency["name"])


for name in ("boto3", "pydantic", "opensearch-py"):
    include(name)
with tempfile.TemporaryDirectory(prefix="smart-beauty-worker-") as directory:
    staging = Path(directory)
    subprocess.run([
        "uv", "pip", "install", "--target", str(staging),
        "--python-platform", "x86_64-manylinux2014", "--python-version", "3.12",
        "--only-binary", ":all:", "--no-deps",
        *[f"{name}=={packages[name]['version']}" for name in sorted(required)],
    ], check=True)
    (staging / "agents").mkdir(exist_ok=True)
    shutil.copyfile(root / "agents/__init__.py", staging / "agents/__init__.py")
    shutil.copyfile(root / "agents/telemetry.py", staging / "agents/telemetry.py")
    shutil.copytree(root / "agents/search", staging / "agents/search", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(root / "catalog_worker/handler.py", staging / "handler.py")
    (staging / "data").mkdir()
    for name in ("search-config.json", "ingredient-registry.json"):
        shutil.copyfile(root / "data" / name, staging / "data" / name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            info = zipfile.ZipInfo(path.relative_to(staging).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o100644 << 16
            archive.writestr(info, path.read_bytes())
print(f"Built {output.relative_to(root)} ({output.stat().st_size} bytes)")
