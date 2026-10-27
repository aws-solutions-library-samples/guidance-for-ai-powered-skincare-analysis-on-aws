"""Check published local links, README section order and Terraform output names."""

from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = [
    "Table of Contents", "Overview", "Prerequisites", "Deployment Steps",
    "Deployment Validation", "Running the Guidance", "Next Steps", "Cleanup",
    "FAQ, Known Issues, Additional Considerations, and Limitations",
    "Revisions", "Notices", "Authors",
]


def anchors(text):
    counts, result = {}, set()
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    return result


def main():
    errors = []
    readme = (ROOT / "README.md").read_text()
    if re.findall(r"^## (.+)$", readme, re.M) != SECTIONS:
        errors.append("README: approved top-level section order changed")
    outputs = set()
    for path in (ROOT / "terraform").glob("*.tf"):
        outputs.update(re.findall(r'output\s+"([^"]+)"', path.read_text()))
    paths = [ROOT / "README.md", ROOT / "tests/README.md", *(ROOT / "docs").rglob("*.md"),
             ROOT / "experiments/search/README.md"]
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text()
        for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            target = match.group(1).strip().split(' "', 1)[0].strip("<>")
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                continue
            destination = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            if not destination.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing link {target}")
            elif parts.fragment and destination.suffix == ".md" and unquote(parts.fragment) not in anchors(destination.read_text()):
                errors.append(f"{path.relative_to(ROOT)}: missing anchor {target}")
        for name in re.findall(r"terraform(?: -chdir=\S+)? output(?: -raw)? ([a-z][a-z_]+)", text):
            if name not in outputs:
                errors.append(f"{path.relative_to(ROOT)}: unknown Terraform output {name}")
    for error in errors:
        print(error)
    if not errors:
        print(f"PASS: README structure, local links in {len(paths)} documents, and referenced Terraform outputs")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
