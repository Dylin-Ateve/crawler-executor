from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    provider: str
    bucket: str
    key: str
    etag: Optional[str]


class ObjectStorageClient(Protocol):
    provider: str
    bucket: str

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        content_encoding: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> StoredObject:
        ...


@dataclass(frozen=True)
class OciObjectStorageConfig:
    namespace: str
    bucket: str
    region: str
    endpoint: str
    auth_mode: str = "api_key"
    config_file: str = "~/.oci/config"
    profile: str = "DEFAULT"


class OciObjectStorageClient:
    provider = "oci"

    def __init__(self, config: OciObjectStorageConfig, client: object) -> None:
        self.config = config
        self.client = client
        self.bucket = config.bucket

    @classmethod
    def from_config(cls, config: OciObjectStorageConfig) -> "OciObjectStorageClient":
        try:
            import oci
        except ImportError as exc:
            raise StorageError("oci package is required for OCI Object Storage") from exc

        auth_mode = config.auth_mode.lower().strip()
        if auth_mode == "api_key":
            oci_config = oci.config.from_file(file_location=config.config_file, profile_name=config.profile)
            if config.region:
                oci_config["region"] = config.region
            client = oci.object_storage.ObjectStorageClient(
                oci_config,
                service_endpoint=config.endpoint or None,
            )
        elif auth_mode == "instance_principal":
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            client = oci.object_storage.ObjectStorageClient(
                {"region": config.region},
                signer=signer,
                service_endpoint=config.endpoint or None,
            )
        else:
            raise StorageError(f"unsupported OCI_AUTH_MODE: {config.auth_mode}")

        return cls(config=config, client=client)

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        content_encoding: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> StoredObject:
        try:
            response = self.client.put_object(
                self.config.namespace,
                self.config.bucket,
                key,
                body,
                content_type=content_type,
                content_encoding=content_encoding,
                opc_meta=metadata or {},
            )
        except Exception as exc:
            raise StorageError(f"failed to upload object key={key}") from exc

        headers = getattr(response, "headers", {}) or {}
        etag = headers.get("etag") or headers.get("ETag")
        return StoredObject(provider=self.provider, bucket=self.config.bucket, key=key, etag=etag)


class FakeObjectStorageClient:
    def __init__(self, bucket: str = "fake-bucket", fail_upload: bool = False, provider: str = "oci") -> None:
        self.provider = provider
        self.bucket = bucket
        self.fail_upload = fail_upload
        self.objects: Dict[str, Dict[str, object]] = {}

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        content_encoding: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> StoredObject:
        if self.fail_upload:
            raise StorageError(f"fake upload failure key={key}")
        self.objects[key] = {
            "body": body,
            "content_type": content_type,
            "content_encoding": content_encoding,
            "metadata": metadata or {},
        }
        return StoredObject(provider=self.provider, bucket=self.bucket, key=key, etag=f"fake-etag-{len(body)}")


def build_object_storage_client(settings) -> ObjectStorageClient:
    provider = settings.get("OBJECT_STORAGE_PROVIDER", "oci").lower().strip()
    if provider != "oci":
        raise StorageError(f"unsupported OBJECT_STORAGE_PROVIDER: {provider}")

    config = OciObjectStorageConfig(
        namespace=settings.get("OCI_OBJECT_STORAGE_NAMESPACE"),
        bucket=settings.get("OCI_OBJECT_STORAGE_BUCKET"),
        region=settings.get("OCI_OBJECT_STORAGE_REGION"),
        endpoint=settings.get("OCI_OBJECT_STORAGE_ENDPOINT"),
        auth_mode=settings.get("OCI_AUTH_MODE", "api_key"),
        config_file=settings.get("OCI_CONFIG_FILE"),
        profile=settings.get("OCI_PROFILE", "DEFAULT"),
    )
    return OciObjectStorageClient.from_config(config)
