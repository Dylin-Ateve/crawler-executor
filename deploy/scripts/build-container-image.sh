#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

IMAGE_NAME="${IMAGE_NAME:-crawler-executor}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo dev)}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-}"
PUSH_IMAGE="${PUSH_IMAGE:-false}"
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-python:3.11-slim}"

if [[ -n "${IMAGE_REF:-}" ]]; then
  image_ref="${IMAGE_REF}"
elif [[ -n "${IMAGE_REGISTRY}" ]]; then
  image_ref="${IMAGE_REGISTRY%/}/${IMAGE_NAME}:${IMAGE_TAG}"
else
  image_ref="${IMAGE_NAME}:${IMAGE_TAG}"
fi

docker build \
  --build-arg "PYTHON_BASE_IMAGE=${PYTHON_BASE_IMAGE}" \
  -f "${ROOT_DIR}/Dockerfile" \
  -t "${image_ref}" \
  "${ROOT_DIR}"

if [[ "${PUSH_IMAGE}" == "true" ]]; then
  docker push "${image_ref}"
fi

echo "${image_ref}"
