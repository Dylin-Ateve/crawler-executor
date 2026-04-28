from types import SimpleNamespace

from crawler.storage import FakeObjectStorageClient, StorageError, _response_body_to_bytes


def test_fake_object_storage_client_reads_uploaded_body():
    client = FakeObjectStorageClient()
    client.put_object("key", b"body", content_type="text/plain")

    assert client.get_object("key") == b"body"


def test_fake_object_storage_client_raises_for_missing_object():
    client = FakeObjectStorageClient()

    try:
        client.get_object("missing")
    except StorageError as exc:
        assert "fake object not found" in str(exc)
    else:
        raise AssertionError("expected StorageError")


def test_response_body_to_bytes_accepts_content_attribute():
    response = SimpleNamespace(data=SimpleNamespace(content=b"body"))

    assert _response_body_to_bytes(response) == b"body"


def test_response_body_to_bytes_accepts_readable_data():
    class Readable:
        def read(self):
            return b"body"

    response = SimpleNamespace(data=Readable())

    assert _response_body_to_bytes(response) == b"body"
