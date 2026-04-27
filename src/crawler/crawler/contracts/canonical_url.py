from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class CanonicalUrlError(ValueError):
    """Raised when a URL cannot be represented by the canonical URL contract."""


@dataclass(frozen=True)
class CanonicalUrl:
    original_url: str
    canonical_url: str
    url_hash: str

    @property
    def dedupe_key(self) -> str:
        return self.url_hash


def canonicalize_url(url: str) -> str:
    """Return the canonical URL used for crawler dedupe and page identity."""

    raw_url = (url or "").strip()
    if not raw_url:
        raise CanonicalUrlError("url is required")

    parsed = urlsplit(raw_url)
    if not parsed.scheme or not parsed.netloc:
        raise CanonicalUrlError(f"absolute URL is required: {url}")

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise CanonicalUrlError(f"URL host is required: {url}")

    try:
        port = parsed.port
    except ValueError as exc:
        raise CanonicalUrlError(f"invalid URL port: {url}") from exc

    netloc = _canonical_netloc(hostname, port, scheme)
    path = _canonical_path(parsed.path)
    query = _canonical_query(parse_qsl(parsed.query, keep_blank_values=True))

    return urlunsplit((scheme, netloc, path, query, ""))


def canonical_url_hash(url: str) -> str:
    canonical = canonicalize_url(url)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_canonical_url(url: str) -> CanonicalUrl:
    canonical = canonicalize_url(url)
    return CanonicalUrl(
        original_url=url,
        canonical_url=canonical,
        url_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _canonical_netloc(hostname: str, port: Optional[int], scheme: str) -> str:
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return hostname
    return f"{hostname}:{port}"


def _canonical_path(path: str) -> str:
    if not path or path == "/":
        return ""
    return path.rstrip("/") or ""


def _canonical_query(pairs: Iterable[Tuple[str, str]]) -> str:
    sorted_pairs = sorted((key, value) for key, value in pairs)
    return urlencode(sorted_pairs, doseq=True)
