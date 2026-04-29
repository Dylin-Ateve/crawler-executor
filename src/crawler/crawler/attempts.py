from __future__ import annotations

from datetime import datetime


def build_attempt_id(url_hash: str, attempted_at: datetime) -> str:
    attempted_at_ms = int(attempted_at.timestamp() * 1000)
    return f"{url_hash}:attempt:{attempted_at_ms}"
