#!/bin/bash
# Trigger CodeBuild and wait for completion
set -e

PROJECT_NAME="$1"
REGION="$2"
REPO_NAME="$3"
IMAGE_TAG="$4"
REPO_URL="$5"

if [ -z "$PROJECT_NAME" ] || [ -z "$REGION" ] || [ -z "$REPO_NAME" ] || [ -z "$IMAGE_TAG" ] || [ -z "$REPO_URL" ]; then
  echo "Usage: $0 <project-name> <region> <repo-name> <image-tag> <repo-url>"
  exit 1
fi

# Check if image already exists in ECR (skip build if tag is immutable and present)
EXISTING_TAG=$(aws ecr describe-images \
  --repository-name "$REPO_NAME" \
  --image-ids imageTag="$IMAGE_TAG" \
  --region "$REGION" \
  --query 'imageDetails[0].imageDigest' \
  --output text 2>/dev/null || true)

if [ -n "$EXISTING_TAG" ] && [ "$EXISTING_TAG" != "None" ]; then
  echo "Image $REPO_URL:$IMAGE_TAG already exists in ECR — skipping build"
  exit 0
fi

echo "Starting CodeBuild project: $PROJECT_NAME"
echo "Target: $REPO_URL:$IMAGE_TAG"

start_build() {
  BUILD_ID=$(aws codebuild start-build \
    --project-name "$PROJECT_NAME" \
    --region "$REGION" \
    --query 'build.id' \
    --output text)
  echo "Build started: $BUILD_ID"
}

# IAM policy creation can finish before CodeBuild observes the new grant.
# Retry only the observed pre-execution log-stream failure, never explicit
# denies or failures after a build phase has started.
retryable_startup_failure() {
  local phase_details
  phase_details=$(aws codebuild batch-get-builds \
    --ids "$BUILD_ID" --region "$REGION" \
    --query 'builds[0].phases' --output json) || return 1
  printf '%s\n' "$phase_details" | python3 -c '
import json, sys
try:
    phases = json.load(sys.stdin)
except (ValueError, TypeError):
    sys.exit(1)
if not isinstance(phases, list) or not phases or any(
    not isinstance(p, dict) or p.get("phaseType") not in ("SUBMITTED", "QUEUED", "COMPLETED")
    for p in phases
):
    sys.exit(1)
retryable = any(
    p.get("phaseType") == "QUEUED" and p.get("phaseStatus") == "CLIENT_ERROR"
    and any(
        isinstance(c, dict) and c.get("statusCode") == "ACCESS_DENIED"
        and isinstance(c.get("message"), str)
        and "logs:CreateLogStream" in c["message"]
        and "because no identity-based policy allows" in c["message"]
        and "explicit deny" not in c["message"].lower()
        for c in (p.get("contexts") or [])
    )
    for p in phases
)
sys.exit(0 if retryable else 1)
'
}

BUILD_ATTEMPT=1
MAX_BUILD_ATTEMPTS=4
start_build

# Poll for completion
while true; do
  BUILD_INFO=$(aws codebuild batch-get-builds \
    --ids "$BUILD_ID" \
    --region "$REGION" \
    --query 'builds[0].[buildStatus,currentPhase]' \
    --output text)
  STATUS=$(echo "$BUILD_INFO" | awk '{print $1}')
  PHASE=$(echo "$BUILD_INFO" | awk '{print $2}')

  echo "  Status: $STATUS | Phase: $PHASE"

  case "$STATUS" in
    SUCCEEDED)
      echo "Build succeeded"
      break
      ;;
    FAILED|FAULT|STOPPED|TIMED_OUT)
      if [ "$STATUS" = "FAILED" ] && [ "$BUILD_ATTEMPT" -lt "$MAX_BUILD_ATTEMPTS" ] && retryable_startup_failure; then
        RETRY_DELAY=$((10 * (1 << (BUILD_ATTEMPT - 1))))
        echo "CodeBuild log permission not yet available; retrying startup in ${RETRY_DELAY}s"
        sleep "$RETRY_DELAY"
        BUILD_ATTEMPT=$((BUILD_ATTEMPT + 1))
        start_build
        continue
      fi
      echo "Build failed with status: $STATUS"
      # Show build logs hint
      echo "Check logs: aws codebuild batch-get-builds --ids $BUILD_ID --region $REGION"
      exit 1
      ;;
    IN_PROGRESS)
      sleep 10
      ;;
    *)
      sleep 5
      ;;
  esac
done

# Verify image exists in ECR
echo "Verifying image in ECR..."
IMAGE_SIZE=$(aws ecr describe-images \
  --repository-name "$REPO_NAME" \
  --image-ids imageTag="$IMAGE_TAG" \
  --region "$REGION" \
  --query 'imageDetails[0].imageSizeInBytes' \
  --output text)

if [ -z "$IMAGE_SIZE" ] || [ "$IMAGE_SIZE" = "None" ]; then
  echo "ERROR: Image $REPO_URL:$IMAGE_TAG not found in ECR"
  exit 1
fi

echo "Image verified: $REPO_URL:$IMAGE_TAG (${IMAGE_SIZE} bytes)"
