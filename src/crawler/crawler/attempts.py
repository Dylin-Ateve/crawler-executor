from __future__ import annotations

import hashlib
from datetime import datetime

from crawler.contracts.canonical_url import canonical_url_hash


def build_attempt_id(url_hash: str, attempted_at: datetime) -> str:
    attempted_at_ms = int(attempted_at.timestamp() * 1000)
    return f"{url_hash}:attempt:{attempted_at_ms}"


def build_command_attempt_id(job_id: str, canonical_url: str) -> str:
    normalized_job_id = (job_id or "").strip()
    normalized_canonical_url = (canonical_url or "").strip()
    if not normalized_job_id:
        raise ValueError("job_id is required")
    if not normalized_canonical_url:
        raise ValueError("canonical_url is required")
    url_hash = canonical_url_hash(normalized_canonical_url)
    identity_hash = hashlib.sha256(f"{normalized_job_id}\0{normalized_canonical_url}".encode("utf-8")).hexdigest()
    return f"{url_hash}:attempt:{identity_hash[:16]}"
