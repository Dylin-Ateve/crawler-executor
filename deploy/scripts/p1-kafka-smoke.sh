#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src/crawler:${PYTHONPATH:-}"

python -m crawler.tools.p1_kafka_smoke
