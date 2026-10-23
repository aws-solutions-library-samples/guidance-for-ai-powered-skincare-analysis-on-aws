#!/bin/bash
# Package agent source code into a zip for S3 upload.
# Called by Terraform with the source files listed in agentcore.tf.
set -euo pipefail

# Prerequisite checks
command -v zip >/dev/null 2>&1 || { echo "ERROR: zip is required but not installed"; exit 1; }
if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <project-relative source file> [...]"
  exit 1
fi

TERRAFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$TERRAFORM_DIR/.." && pwd)"
BUILD_DIR="$TERRAFORM_DIR/.build"
STAGE="$BUILD_DIR/agent-code"

rm -rf "$STAGE"
mkdir -p "$STAGE"

for source_file in "$@"; do
  mkdir -p "$(dirname "$STAGE/$source_file")"
  cp "$PROJECT_ROOT/$source_file" "$STAGE/$source_file"
done

# Recreate the archive so deleted source files cannot survive a later build.
rm -f "$BUILD_DIR/agent-code.zip"
cd "$STAGE" && zip -qr "$BUILD_DIR/agent-code.zip" .
