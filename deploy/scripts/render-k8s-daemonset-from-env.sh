#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
IMAGE_REF="${IMAGE_REF:-crawler-executor:CHANGE_ME}"

"${PYTHON_BIN}" - "${ROOT_DIR}/deploy/k8s/base/daemonset.yaml" "${IMAGE_REF}" <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
image_ref = sys.argv[2]
node_key = os.getenv("M3_NODE_SELECTOR_KEY", "scrapy-egress")
node_value = os.getenv("M3_NODE_SELECTOR_VALUE", "true")
image_pull_secret = os.getenv("M3_IMAGE_PULL_SECRET", "regcred")
taint_enabled = os.getenv("M3_NODE_TAINT_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

text = path.read_text(encoding="utf-8")
text = text.replace("image: crawler-executor:CHANGE_ME", f"image: {image_ref}")
text = text.replace("scrapy-egress: \"true\"", f"{node_key}: \"{node_value}\"")
text = text.replace("name: regcred", f"name: {image_pull_secret}")

if taint_enabled:
    text = text.replace("key: scrapy-egress", f"key: {node_key}")
    text = text.replace('value: "true"', f'value: "{node_value}"', 1)
else:
    lines = text.splitlines()
    rendered: list[str] = []
    skip = False
    for line in lines:
        if line.strip() == "tolerations:":
            skip = True
            continue
        if skip:
            if line.startswith("      containers:"):
                skip = False
                rendered.append(line)
            continue
        rendered.append(line)
    text = "\n".join(rendered) + "\n"

sys.stdout.write(text)
PY
