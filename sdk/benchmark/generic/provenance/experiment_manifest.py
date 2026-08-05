"""Resolved experiment manifest helpers for Generic Benchmark runs."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import tempfile
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


try:
    from common.secret_refs import is_sensitive_key
except ImportError:  # Package import in tests.
    from ..common.secret_refs import is_sensitive_key

MANIFEST_SCHEMA_VERSION = 3
TOOL_SCHEMA_FIELDS = (
    "class_name",
    "name",
    "description",
    "inputs",
    "output_type",
    "params",
    "source",
    "usage",
    "labels",
)
MAX_SERIALIZATION_DEPTH = 50


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically for hashing and persistence."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_value(value: Any) -> str:
    """Return a stable SHA-256 digest for a JSON-compatible value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def resolve_code_commit(repo_root: Path) -> str:
    """Resolve the exact Git commit used by the benchmark."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def compute_source_tree_hash(repo_root: Path) -> str:
    """Compute a content hash of the tracked working tree via a temporary Git index.

    Uses a temporary index file to:
    1. git read-tree HEAD
    2. git add -u (update index with working tree changes)
    3. git write-tree (produce a tree hash)

    This does NOT modify the real index, working tree, or create any commit.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="bench_idx_")
    os.close(tmp_fd)
    try:
        env = {**os.environ, "GIT_INDEX_FILE": tmp_path}
        subprocess.run(
            ["git", "read-tree", "HEAD"],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", "-u"],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            ["git", "write-tree"],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        return f"error:{exc.stderr.strip() or exc.cmd}"
    except FileNotFoundError:
        return "error:git not found"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


_UNTRACKED_EXCLUDE_DIRS = {"artifacts", "__pycache__", ".pytest_cache"}
_UNTRACKED_EXCLUDE_SUFFIXES = {".pyc"}
_UNTRACKED_INCLUDE_PATTERNS = ("sdk/", "backend/")
_UNTRACKED_INCLUDE_SUFFIXES = (".yaml", ".yml")


def check_untracked_risk(repo_root: Path) -> dict[str, Any]:
    """Check for untracked files that may participate in benchmark execution."""
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked_dirty = any(
        line[:2] != "??" for line in status_result.stdout.splitlines() if line.strip()
    )

    untracked_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    relevant: list[str] = []
    for raw_path in untracked_result.stdout.splitlines():
        path = raw_path.strip()
        if not path:
            continue
        parts = Path(path).parts
        if any(part in _UNTRACKED_EXCLUDE_DIRS for part in parts):
            continue
        if any(path.endswith(suffix) for suffix in _UNTRACKED_EXCLUDE_SUFFIXES):
            continue
        is_relevant = (
            any(path.startswith(prefix) for prefix in _UNTRACKED_INCLUDE_PATTERNS)
            or any(path.endswith(suffix) for suffix in _UNTRACKED_INCLUDE_SUFFIXES)
        )
        if is_relevant:
            relevant.append(path)

    return {
        "tracked_worktree_dirty": tracked_dirty,
        "relevant_untracked_files": sorted(relevant),
        "source_snapshot_method": "temporary_index_write_tree_v1",
    }


def build_manifest(
    *,
    dataset_name: str,
    dataset_version: str | None,
    dataset_item_ids: list[str],
    run_name: str,
    repo_root: Path,
    lifecycle_mode: str,
    context_manager_config: Any,
    max_steps: int,
    temperature: float,
    language: str,
    max_concurrency: int,
    model_config: dict[str, Any],
    tools: list[Any],
    system_prompt: str,
    agent_config: dict[str, Any],
    evaluator_names: list[str],
    observation_policy: dict[str, Any],
    parity_snapshot: dict[str, Any] | None = None,
    parity_gate: dict[str, Any] | None = None,
    budget_profile: str = "legacy_threshold",
    started_at: str | None = None,
) -> dict[str, Any]:
    """Build a manifest from final effective values, not raw CLI inputs."""
    cm_config = _jsonable(context_manager_config)
    _resolve_cm_budget_defaults(cm_config)
    processing_mode = _processing_mode(cm_config)
    tool_payload = _tool_schema_payload(tools)
    model_endpoint = _sanitize_endpoint(
        model_config.get("url") or model_config.get("base_url") or ""
    )

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "dataset_item_ids": dataset_item_ids,
        "run_name": run_name,
        "code_commit": resolve_code_commit(repo_root),
        "source_tree_hash": compute_source_tree_hash(repo_root),
        **check_untracked_risk(repo_root),
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
        "environment": {
            "hostname": platform.node(),
            "python_version": platform.python_version(),
        },
        "benchmark_lifecycle_mode": lifecycle_mode,
        "context_runtime": "context_items",
        "context_processing_mode": processing_mode,
        "adaptive_compaction_enabled": processing_mode == "adaptive_compact",
        "context_policy_fingerprint": sha256_value(
            (cm_config.get("policy_layers") or {}).get("platform") or {}
        ),
        "context_manager": cm_config,
        "main_model": model_config.get("model_name", ""),
        "summary_model": model_config.get("model_name", ""),
        "summary_uses_main_model": True,
        "model_endpoint": model_endpoint,
        "model_provider": _provider_from_endpoint(model_endpoint),
        "model_factory": model_config.get("model_factory"),
        "temperature": temperature,
        "max_steps": max_steps,
        "language": language,
        "max_concurrency": max_concurrency,
        "tool_count": len(tool_payload),
        "tool_schema_hash": sha256_value(tool_payload),
        "system_prompt_hash": sha256_value(system_prompt),
        "agent_config_hash": sha256_value(agent_config),
        "evaluator_names": evaluator_names,
        "evaluator_version": "code_commit",
        "context_item_types": agent_config.get("context_item_types", []),
        "observation_policy": observation_policy,
        "parity_snapshot": parity_snapshot or {},
        "parity_snapshot_hash": sha256_value(parity_snapshot or {}),
        "parity_gate": parity_gate or {
            "passed": None,
            "simulation_fidelity": "mechanism_only",
        },
        "budget_profile": budget_profile,
    }
    manifest["manifest_hash"] = sha256_value(manifest)
    return manifest


def write_manifest_exclusive(manifest: dict[str, Any], output_dir: Path) -> Path:
    """Persist a manifest without ever overwriting an existing run artifact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path(output_dir, manifest["run_name"])
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def manifest_path(output_dir: Path, run_name: str) -> Path:
    """Return the canonical local manifest path for a run name."""
    safe_run_name = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in run_name
    )
    return output_dir / f"{safe_run_name}.manifest.json"


def _tool_schema_payload(tools: list[Any]) -> list[dict[str, Any]]:
    """Project runtime ToolConfig objects to stable, credential-free schemas."""
    payload = []
    for tool in tools:
        if isinstance(tool, dict):
            schema = {
                field: tool[field]
                for field in TOOL_SCHEMA_FIELDS
                if field in tool
            }
        else:
            schema = {
                field: getattr(tool, field)
                for field in TOOL_SCHEMA_FIELDS
                if hasattr(tool, field)
            }
        payload.append(_jsonable(schema))
    return payload


def _jsonable(
    value: Any,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> Any:
    """Convert values safely, stopping cycles and excluding runtime internals."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if _depth >= MAX_SERIALIZATION_DEPTH:
        return f"[MAX_DEPTH:{type(value).__name__}]"

    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return f"[CYCLE:{type(value).__name__}]"
    seen.add(identity)
    next_depth = _depth + 1

    if is_dataclass(value):
        result = {
            field.name: _jsonable(
                getattr(value, field.name),
                _seen=seen,
                _depth=next_depth,
            )
            for field in fields(value)
        }
        seen.remove(identity)
        return result
    if isinstance(value, dict):
        result = {
            str(key): (
                "[REDACTED]"
                if is_sensitive_key(key)
                else _jsonable(item, _seen=seen, _depth=next_depth)
            )
            for key, item in value.items()
        }
        seen.remove(identity)
        return result
    if isinstance(value, (list, tuple, set)):
        result = [
            _jsonable(item, _seen=seen, _depth=next_depth)
            for item in value
        ]
        seen.remove(identity)
        return result
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(exclude={"metadata"})
        except (RecursionError, TypeError, ValueError):
            dumped = None
        if dumped is not None:
            result = _jsonable(dumped, _seen=seen, _depth=next_depth)
            seen.remove(identity)
            return result
    if hasattr(value, "__dict__"):
        public = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
            and not is_sensitive_key(key)
            and key != "metadata"
        }
        result = _jsonable(public, _seen=seen, _depth=next_depth)
        seen.remove(identity)
        return result
    seen.remove(identity)
    return str(value)


def _sanitize_endpoint(endpoint: str) -> str:
    if not endpoint:
        return ""
    parsed = urlsplit(endpoint)
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def _provider_from_endpoint(endpoint: str) -> str:
    lowered = endpoint.lower()
    for provider in ("openai", "anthropic", "azure", "volcengine", "aliyun"):
        if provider in lowered:
            return provider
    return "unknown"


def _resolve_cm_budget_defaults(cm_config: dict[str, Any]) -> None:
    """Replace zero-default budget fields with their resolved runtime values.

    ``ContextManagerConfig`` uses ``0`` as a sentinel meaning "derive from
    token_threshold".  ``ContextManager`` resolves these at runtime via
    ``_soft_input_budget_tokens`` / ``_hard_input_budget_tokens`` etc.
    The manifest must record the resolved values so historical runs remain
    reproducible even if the derivation logic changes later.
    """
    threshold = cm_config.get("token_threshold") or 0
    if threshold <= 0:
        return

    _resolvable = {
        "soft_input_budget_tokens": threshold,
        "hard_input_budget_tokens": int(threshold * 1.1),
        "max_summary_input_tokens": int(threshold * 1.2),
        "max_summary_reduce_tokens": int(threshold * 0.2),
    }
    for field, resolved in _resolvable.items():
        if not cm_config.get(field):
            cm_config[field] = resolved


def _processing_mode(cm_config: dict[str, Any]) -> str:
    """Read the resolved platform policy from a serialized config."""
    layers = cm_config.get("policy_layers") or {}
    platform_policy = layers.get("platform") or {}
    return str(platform_policy.get("processing_mode") or "passthrough")
