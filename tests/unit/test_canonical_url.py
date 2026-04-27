import pytest

from crawler.contracts.canonical_url import (
    CanonicalUrlError,
    build_canonical_url,
    canonical_url_hash,
    canonicalize_url,
)


def test_canonical_url_ignores_fragment_host_case_default_port_and_trailing_slash():
    assert (
        canonicalize_url("HTTPS://Example.COM:443/a/b/?b=2&a=1#section")
        == "https://example.com/a/b?a=1&b=2"
    )


def test_canonical_url_ignores_query_order():
    assert canonicalize_url("https://example.com/search?b=2&a=1") == canonicalize_url(
        "https://EXAMPLE.com/search?a=1&b=2#ignored"
    )


def test_canonical_url_treats_root_path_and_empty_path_as_same():
    assert canonicalize_url("https://example.com/") == "https://example.com"
    assert canonicalize_url("https://example.com") == "https://example.com"


def test_canonical_url_preserves_non_default_port_and_path_case():
    assert canonicalize_url("https://example.com:8443/Path") == "https://example.com:8443/Path"


def test_canonical_url_preserves_repeated_query_values_in_sorted_order():
    assert canonicalize_url("https://example.com/?tag=b&tag=a") == "https://example.com?tag=a&tag=b"


def test_canonical_url_hash_uses_canonical_form():
    assert canonical_url_hash("https://example.com?a=1&b=2#x") == canonical_url_hash(
        "https://EXAMPLE.com/?b=2&a=1"
    )


def test_build_canonical_url_exposes_dedupe_key():
    canonical = build_canonical_url("https://example.com/path/")

    assert canonical.canonical_url == "https://example.com/path"
    assert canonical.dedupe_key == canonical.url_hash


def test_canonical_url_requires_absolute_url():
    with pytest.raises(CanonicalUrlError):
        canonicalize_url("/relative/path")

