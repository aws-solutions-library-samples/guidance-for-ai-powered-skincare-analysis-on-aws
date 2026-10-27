"""Build a deterministic Lambda archive after `npm ci` in api_proxy/."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
source = root / "api_proxy"
if not (source / "node_modules/@aws-sdk/client-bedrock-agentcore/package.json").is_file():
    raise SystemExit("Run npm ci in api_proxy/ before building.")
output = source / ".build/function.zip"
output.parent.mkdir(exist_ok=True)
paths = [*source.glob("*.mjs"), source / "package.json"]
paths += [path for path in (source / "node_modules").rglob("*") if path.is_file()]
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(paths):
        info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, path.read_bytes())
print(f"Built {output.relative_to(root)} ({output.stat().st_size} bytes)")
