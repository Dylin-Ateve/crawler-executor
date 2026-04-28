from __future__ import annotations

from typing import Dict, Iterable


class SchemaValidationError(ValueError):
    pass


PAGE_METADATA_SCHEMA_VERSION = "1.0"

PAGE_METADATA_REQUIRED_FIELDS = {
    "schema_version",
    "snapshot_id",
    "url_hash",
    "canonical_url",
    "original_url",
    "host",
    "fetched_at",
    "status_code",
    "content_sha256",
    "storage_provider",
    "bucket",
    "storage_key",
    "compression",
}


def validate_page_metadata(payload: Dict[str, object]) -> None:
    missing = sorted(field for field in PAGE_METADATA_REQUIRED_FIELDS if payload.get(field) in (None, ""))
    if missing:
        raise SchemaValidationError(f"page metadata missing required fields: {', '.join(missing)}")
    if payload.get("schema_version") != PAGE_METADATA_SCHEMA_VERSION:
        raise SchemaValidationError(f"unsupported schema_version: {payload.get('schema_version')}")
    if not _is_hex_sha256(str(payload.get("content_sha256", ""))):
        raise SchemaValidationError("content_sha256 must be a lowercase sha256 hex digest")
    status_code = payload.get("status_code")
    if not isinstance(status_code, int) or status_code < 100 or status_code > 599:
        raise SchemaValidationError("status_code must be an integer HTTP status")
    if payload.get("storage_provider") != "oci":
        raise SchemaValidationError("storage_provider must be oci")
    if payload.get("compression") != "gzip":
        raise SchemaValidationError("compression must be gzip")


def _is_hex_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def filter_headers(headers: Dict[str, str], allowed: Iterable[str]) -> Dict[str, str]:
    allowed_lower = {header.lower() for header in allowed}
    return {key.lower(): value for key, value in headers.items() if key.lower() in allowed_lower}
