#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ENV_DIR="$REPO_ROOT/deploy/terraform/envs/edge-lambda"

cd "$ENV_DIR"

# With TF_STATE_BUCKET exported, use the same shared state as the CI workflow;
# without it, keep the local backend.tf (see README, "Deploy").
if [ -n "${TF_STATE_BUCKET:-}" ]; then
  "$REPO_ROOT/deploy/ci/render-backend.sh"
fi

terraform init
terraform apply -auto-approve -target=aws_ecr_repository.app

REPOSITORY="$(terraform output -raw ecr_repository_url)"
REGION="$(terraform output -raw aws_region)"
TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
IMAGE="$REPOSITORY:$TAG"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${REPOSITORY%%/*}"

docker buildx build \
  --platform linux/amd64 \
  -f "$REPO_ROOT/deploy/docker/Dockerfile.lambda" \
  -t "$IMAGE" \
  --push \
  "$REPO_ROOT"

terraform apply -auto-approve -var="image_uri=$IMAGE"
terraform output
