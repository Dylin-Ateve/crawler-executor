#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${IMAGE_REF:-}" ]]; then
  echo "set_daemonset_image_failed: IMAGE_REF is required"
  exit 2
fi

NAMESPACE="${M3_K8S_NAMESPACE:-crawler-executor}"
DAEMONSET="${M3_DAEMONSET_NAME:-crawler-executor}"
CONTAINER="${M3_CONTAINER_NAME:-crawler-executor}"

kubectl -n "${NAMESPACE}" set image "daemonset/${DAEMONSET}" "${CONTAINER}=${IMAGE_REF}"

echo "daemonset_image_updated namespace=${NAMESPACE} daemonset=${DAEMONSET} container=${CONTAINER} image=${IMAGE_REF}"
echo "note: updateStrategy=OnDelete; delete target pods manually after validation to recreate them with the new image."
