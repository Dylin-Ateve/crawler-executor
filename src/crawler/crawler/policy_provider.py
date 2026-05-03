from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from crawler.metrics import metrics
from crawler.runtime_policy import (
    EffectivePolicyDocument,
    RuntimePolicyError,
    make_bootstrap_policy_document,
    policy_document_from_mapping,
)


@dataclass(frozen=True)
class PolicySnapshot:
    document: EffectivePolicyDocument
    lkg_active: bool
    load_result: str
    error: Optional[str] = None
    loaded_at: Optional[float] = None


class RuntimePolicyProvider:
    def current(self, *, force: bool = False) -> PolicySnapshot:
        raise NotImplementedError


class StaticRuntimePolicyProvider(RuntimePolicyProvider):
    def __init__(self, document: EffectivePolicyDocument) -> None:
        self.document = document
        self.loaded_at = time.time()

    def current(self, *, force: bool = False) -> PolicySnapshot:
        return PolicySnapshot(self.document, lkg_active=False, load_result="not_modified", loaded_at=self.loaded_at)


class FileRuntimePolicyProvider(RuntimePolicyProvider):
    def __init__(
        self,
        path: str,
        *,
        bootstrap_document: EffectivePolicyDocument,
        reload_interval_seconds: int = 30,
    ) -> None:
        self.path = Path(path)
        self.bootstrap_document = bootstrap_document
        self.reload_interval_seconds = max(int(reload_interval_seconds), 1)
        self._current_document: EffectivePolicyDocument = bootstrap_document
        self._last_known_good: Optional[EffectivePolicyDocument] = None
        self._last_loaded_at: Optional[float] = None
        self._last_checked_at = 0.0
        self._last_mtime_ns: Optional[int] = None
        self._last_result = "bootstrap"
        self._last_error: Optional[str] = None

    def current(self, *, force: bool = False) -> PolicySnapshot:
        now = time.time()
        if not force and now - self._last_checked_at < self.reload_interval_seconds:
            self._record_state()
            return PolicySnapshot(
                self._current_document,
                lkg_active=self._is_lkg_active(),
                load_result="not_modified",
                error=self._last_error,
                loaded_at=self._last_loaded_at,
            )
        self._last_checked_at = now

        try:
            stat = self.path.stat()
            if self._last_mtime_ns == stat.st_mtime_ns and self._last_known_good is not None:
                self._last_result = "not_modified"
                self._last_error = None
                metrics.record_policy_load("not_modified")
                self._record_state()
                return PolicySnapshot(
                    self._current_document,
                    lkg_active=self._is_lkg_active(),
                    load_result="not_modified",
                    loaded_at=self._last_loaded_at,
                )
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            document = policy_document_from_mapping(loaded)
        except OSError as exc:
            return self._handle_failure("read_error", str(exc))
        except json.JSONDecodeError as exc:
            return self._handle_failure("validation_error", f"invalid json: {exc}")
        except RuntimePolicyError as exc:
            return self._handle_failure("validation_error", str(exc))

        self._current_document = document
        self._last_known_good = document
        self._last_loaded_at = now
        self._last_mtime_ns = stat.st_mtime_ns
        self._last_result = "success"
        self._last_error = None
        metrics.record_policy_load("success")
        self._record_state()
        return PolicySnapshot(document, lkg_active=False, load_result="success", loaded_at=self._last_loaded_at)

    def _handle_failure(self, result: str, error: str) -> PolicySnapshot:
        metrics.record_policy_load(result)
        self._last_result = result
        self._last_error = error
        if self._last_known_good is not None:
            self._current_document = self._last_known_good
        else:
            self._current_document = self.bootstrap_document
        self._record_state()
        return PolicySnapshot(
            self._current_document,
            lkg_active=self._is_lkg_active(),
            load_result=result,
            error=error,
            loaded_at=self._last_loaded_at,
        )

    def _is_lkg_active(self) -> bool:
        return self._last_known_good is not None and self._last_result in {"read_error", "validation_error"}

    def _record_state(self) -> None:
        metrics.set_policy_current_version(self._current_document.version)
        lkg_active = self._is_lkg_active()
        metrics.set_policy_lkg_active(lkg_active)
        if lkg_active and self._last_loaded_at is not None:
            metrics.set_policy_lkg_age(max(time.time() - self._last_loaded_at, 0.0))
        else:
            metrics.set_policy_lkg_age(0.0)


def build_runtime_policy_provider(settings) -> RuntimePolicyProvider:
    bootstrap = make_bootstrap_policy_document(settings)
    provider_type = (settings.get("RUNTIME_POLICY_PROVIDER", "none") or "none").strip().lower()
    if provider_type in {"", "none", "static"}:
        return StaticRuntimePolicyProvider(bootstrap)
    if provider_type in {"file", "configmap", "configmap_file"}:
        path = settings.get("RUNTIME_POLICY_FILE", "") or ""
        if not path:
            return StaticRuntimePolicyProvider(bootstrap)
        return FileRuntimePolicyProvider(
            path,
            bootstrap_document=bootstrap,
            reload_interval_seconds=settings.getint("RUNTIME_POLICY_RELOAD_INTERVAL_SECONDS", 30),
        )
    raise RuntimePolicyError(f"unsupported RUNTIME_POLICY_PROVIDER: {provider_type}")
