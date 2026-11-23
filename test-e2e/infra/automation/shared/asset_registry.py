"""Batch-scoped test asset registry.

Dynamic product assets are written under RESULT_DIR so later D3, D4 and D5
stages can reuse assets that earlier test cases actually created.  Static file
assets and long-lived anchors remain in config/.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from shared.config import test_root


_LOCK = threading.RLock()


@dataclass
class AssetDependencyError(RuntimeError):
    section: str
    key: str
    consumer_case_id: str = ""
    dependency_case_id: str = ""
    detail: str = ""

    def __str__(self) -> str:
        dependency = f"; dependency={self.dependency_case_id}" if self.dependency_case_id else ""
        consumer = f"; consumer={self.consumer_case_id}" if self.consumer_case_id else ""
        detail = f"; {self.detail}" if self.detail else ""
        return f"required test asset is not READY: {self.section}.{self.key}{dependency}{consumer}{detail}"


class AssetTimeoutError(TimeoutError):
    """A product asset did not reach READY within its configured deadline."""


class AutomationInfrastructureError(RuntimeError):
    """The test harness cannot safely create, persist or clean an asset."""


def _result_dir(required: bool = False) -> Path | None:
    configured = os.environ.get("RESULT_DIR", "").strip()
    if not configured:
        if required:
            raise AutomationInfrastructureError("RESULT_DIR is required for dynamic test assets")
        return None
    return Path(configured).resolve()


def runtime_dir(required: bool = False) -> Path | None:
    root = _result_dir(required=required)
    if root is None:
        return None
    path = root / "runtime"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def registry_path() -> Path | None:
    root = runtime_dir()
    return root / "resolved-assets.yaml" if root else None


def journal_path() -> Path | None:
    root = runtime_dir()
    return root / "asset-journal.jsonl" if root else None


def _load_mapping(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise AutomationInfrastructureError(f"asset file must contain a mapping: {path}")
    return value


def _config_mapping(name: str) -> dict[str, Any]:
    path = test_root() / "config" / name
    return _load_mapping(path)


def _atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _append_journal(event: dict[str, Any]) -> None:
    path = journal_path()
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _event(section: str, key: str, state: str, owner_case_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "batch": os.environ.get("TEST_BATCH") or (_result_dir() or Path("unknown")).name,
        "section": section,
        "key": key,
        "state": state,
        "owner_case_id": owner_case_id,
        **extra,
    }


def register_asset(
    section: str,
    key: str,
    value: Any,
    *,
    owner_case_id: str,
    state: str = "READY",
    source: str = "dynamic",
    cleanup: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    sensitive: bool = False,
) -> Any:
    """Persist one non-secret runtime asset for later stages."""
    if value in (None, "", []):
        raise AutomationInfrastructureError(f"cannot register empty asset {section}.{key}")
    path = registry_path()
    if path is None:
        raise AutomationInfrastructureError("RESULT_DIR is required to register dynamic assets")
    entry = {
        "value": value,
        "state": state,
        "source": source,
        "owner_case_id": owner_case_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sensitive": sensitive,
    }
    if cleanup:
        entry["cleanup"] = cleanup
    if metadata:
        entry["metadata"] = metadata
    with _LOCK:
        payload = _load_mapping(path)
        payload.setdefault("schema_version", 1)
        payload.setdefault("batch", os.environ.get("TEST_BATCH") or (_result_dir() or Path("unknown")).name)
        assets = payload.setdefault("assets", {})
        assets.setdefault(section, {})[key] = entry
        _atomic_yaml(path, payload)
        _append_journal(_event(
            section, key, state, owner_case_id, source=source,
            value="***" if sensitive else value,
        ))
    return value


def register_asset_failure(
    section: str,
    key: str,
    *,
    owner_case_id: str,
    reason: str,
    state: str = "FAILED",
) -> None:
    path = registry_path()
    if path is None:
        return
    entry = {
        "state": state,
        "source": "dynamic",
        "owner_case_id": owner_case_id,
        "failure_reason": reason[:1000],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _LOCK:
        payload = _load_mapping(path)
        payload.setdefault("schema_version", 1)
        payload.setdefault("batch", os.environ.get("TEST_BATCH") or (_result_dir() or Path("unknown")).name)
        payload.setdefault("assets", {}).setdefault(section, {})[key] = entry
        _atomic_yaml(path, payload)
        _append_journal(_event(section, key, state, owner_case_id, reason=reason[:1000]))


def mark_asset_state(section: str, key: str, state: str, *, detail: str = "") -> None:
    path = registry_path()
    if path is None:
        return
    with _LOCK:
        payload = _load_mapping(path)
        entry = payload.get("assets", {}).get(section, {}).get(key)
        if not isinstance(entry, dict):
            return
        entry["state"] = state
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        if detail:
            entry["state_detail"] = detail[:1000]
        _atomic_yaml(path, payload)
        _append_journal(_event(section, key, state, str(entry.get("owner_case_id") or ""), detail=detail[:1000]))


def _entry_value(entry: Any) -> tuple[Any, str, str]:
    if isinstance(entry, dict) and "state" in entry:
        return entry.get("value"), str(entry.get("state") or ""), str(entry.get("owner_case_id") or "")
    return entry, "READY", ""


def resolve_asset(
    section: str,
    key: str,
    *,
    required: bool = True,
    consumer_case_id: str = "",
    dependency_case_id: str = "",
) -> Any:
    """Resolve dynamic READY asset, then anchor, then static configuration."""
    path = registry_path()
    dynamic = _load_mapping(path).get("assets", {}).get(section, {}).get(key)
    dynamic_detail = ""
    if dynamic is not None:
        value, state, owner = _entry_value(dynamic)
        if state == "READY" and value not in (None, "", []):
            return value
        dependency_case_id = dependency_case_id or owner
        dynamic_detail = f"dynamic asset state={state or 'UNKNOWN'}"
        # A failed/deleted current-batch asset must never be replaced by a
        # historical anchor with the same key. That would hide the producer
        # failure and may let the test mutate another batch's resource.
        if required:
            raise AssetDependencyError(section, key, consumer_case_id, dependency_case_id, detail=dynamic_detail)
        return None

    for filename in ("anchor-assets.yaml", "test-assets.yaml"):
        value = _config_mapping(filename).get(section, {}).get(key)
        value, state, owner = _entry_value(value)
        if state == "READY" and value not in (None, "", []):
            return value
        dependency_case_id = dependency_case_id or owner

    if required:
        raise AssetDependencyError(section, key, consumer_case_id, dependency_case_id, detail=dynamic_detail)
    return None


def all_registered_assets() -> dict[str, Any]:
    return _load_mapping(registry_path()).get("assets", {})
