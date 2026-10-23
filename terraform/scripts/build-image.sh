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

# Start the build
BUILD_ID=$(aws codebuild start-build \
  --project-name "$PROJECT_NAME" \
  --region "$REGION" \
  --query 'build.id' \
  --output text)

echo "Build started: $BUILD_ID"

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
