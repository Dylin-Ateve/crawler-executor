from crawler import publisher
from crawler.publisher import DEFAULT_SSL_CA_LOCATION, resolve_ssl_ca_location


def test_resolve_ssl_ca_location_uses_existing_configured_path(tmp_path):
    ca_file = tmp_path / "ca-bundle.crt"
    ca_file.write_text("test-ca", encoding="utf-8")

    assert resolve_ssl_ca_location(str(ca_file)) == str(ca_file)


def test_resolve_ssl_ca_location_falls_back_to_existing_common_path(tmp_path, monkeypatch):
    ca_file = tmp_path / "fallback-ca-bundle.crt"
    ca_file.write_text("test-ca", encoding="utf-8")
    monkeypatch.setattr(publisher, "COMMON_SSL_CA_LOCATIONS", (str(ca_file),))

    assert resolve_ssl_ca_location("/missing/cert.pem") == str(ca_file)


def test_resolve_ssl_ca_location_preserves_configured_path_when_no_file_exists(monkeypatch):
    monkeypatch.setattr(publisher, "COMMON_SSL_CA_LOCATIONS", ("/missing/fallback.pem",))

    assert resolve_ssl_ca_location("/missing/cert.pem") == "/missing/cert.pem"


def test_resolve_ssl_ca_location_uses_default_when_unset_and_no_file_exists(monkeypatch):
    monkeypatch.setattr(publisher, "COMMON_SSL_CA_LOCATIONS", ("/missing/fallback.pem",))

    assert resolve_ssl_ca_location("") == DEFAULT_SSL_CA_LOCATION
