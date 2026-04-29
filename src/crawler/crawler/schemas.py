from __future__ import annotations

from typing import Dict, Iterable


class SchemaValidationError(ValueError):
    pass


PAGE_METADATA_SCHEMA_VERSION = "1.0"
CRAWL_ATTEMPT_SCHEMA_VERSION = "1.0"

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


CRAWL_ATTEMPT_REQUIRED_FIELDS = {
    "schema_version",
    "attempt_id",
    "url_hash",
    "canonical_url",
    "original_url",
    "host",
    "attempted_at",
    "finished_at",
    "fetch_result",
    "content_result",
    "storage_result",
}

FETCH_RESULTS = {"succeeded", "failed"}
CONTENT_RESULTS = {"html_snapshot_candidate", "non_snapshot", "unknown"}
STORAGE_RESULTS = {"stored", "failed", "skipped"}


def validate_crawl_attempt(payload: Dict[str, object]) -> None:
    missing = sorted(field for field in CRAWL_ATTEMPT_REQUIRED_FIELDS if payload.get(field) in (None, ""))
    if missing:
        raise SchemaValidationError(f"crawl attempt missing required fields: {', '.join(missing)}")
    if payload.get("schema_version") != CRAWL_ATTEMPT_SCHEMA_VERSION:
        raise SchemaValidationError(f"unsupported schema_version: {payload.get('schema_version')}")
    if not _is_hex_sha256(str(payload.get("url_hash", ""))):
        raise SchemaValidationError("url_hash must be a lowercase sha256 hex digest")
    status_code = payload.get("status_code")
    if status_code is not None and (not isinstance(status_code, int) or status_code < 100 or status_code > 599):
        raise SchemaValidationError("status_code must be null or an integer HTTP status")
    if payload.get("fetch_result") not in FETCH_RESULTS:
        raise SchemaValidationError("fetch_result is invalid")
    if payload.get("content_result") not in CONTENT_RESULTS:
        raise SchemaValidationError("content_result is invalid")
    if payload.get("storage_result") not in STORAGE_RESULTS:
        raise SchemaValidationError("storage_result is invalid")

    content_sha256 = payload.get("content_sha256")
    if content_sha256 is not None and not _is_hex_sha256(str(content_sha256)):
        raise SchemaValidationError("content_sha256 must be null or a lowercase sha256 hex digest")

    if payload.get("storage_result") == "stored":
        stored_required = {
            "snapshot_id",
            "storage_provider",
            "bucket",
            "storage_key",
            "compression",
            "content_sha256",
        }
        missing_stored = sorted(field for field in stored_required if payload.get(field) in (None, ""))
        if missing_stored:
            raise SchemaValidationError(f"stored crawl attempt missing fields: {', '.join(missing_stored)}")
        if payload.get("storage_provider") != "oci":
            raise SchemaValidationError("storage_provider must be oci when storage_result is stored")
        if payload.get("compression") != "gzip":
            raise SchemaValidationError("compression must be gzip when storage_result is stored")


def _is_hex_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def filter_headers(headers: Dict[str, str], allowed: Iterable[str]) -> Dict[str, str]:
    allowed_lower = {header.lower() for header in allowed}
    return {key.lower(): value for key, value in headers.items() if key.lower() in allowed_lower}
