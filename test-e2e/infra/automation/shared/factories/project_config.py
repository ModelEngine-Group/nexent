"""Crash-safe restoration of the four project-config files used by one case."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from shared.asset_registry import mark_asset_state, register_asset
from shared.deployment_paths import mutate_project_config, project_config_dir


def _owned_path(relative: str) -> Path:
    allowed = {
        "modelengine-logo.png", "modelengine-logo2.png",
        "locales/zh/custom.json", "locales/en/custom.json",
    }
    if relative not in allowed:
        raise ValueError(f"unapproved project-config file: {relative}")
    root = project_config_dir()
    target = root / relative
    if target.is_symlink() or root not in target.resolve().parents:
        raise ValueError(f"project-config path escapes deployment mount: {relative}")
    return target


def journal_project_config(relative: str, *, case_id: str, marker: str, expected_logo: bytes) -> None:
    target = _owned_path(relative)
    original = target.read_bytes() if target.is_file() else None
    register_asset(
        "project_config_snapshots", relative.replace("/", "_"), relative,
        owner_case_id=case_id,
        cleanup={
            "kind": "restore_project_config_file", "relative": relative,
            "original_b64": base64.b64encode(original).decode("ascii") if original is not None else None,
            "original_sha256": hashlib.sha256(original).hexdigest() if original is not None else None,
            "marker": marker,
            "logo_sha256": hashlib.sha256(expected_logo).hexdigest(),
        },
    )


def restore_project_config_file(cleanup: dict) -> None:
    relative = str(cleanup["relative"])
    target = _owned_path(relative)
    current = target.read_bytes() if target.is_file() else None
    original_b64 = cleanup.get("original_b64")
    original = base64.b64decode(original_b64) if original_b64 is not None else None
    if current == original:
        mark_asset_state("project_config_snapshots", relative.replace("/", "_"), "DELETED")
        return
    if current is None:
        raise RuntimeError(f"project-config file disappeared outside the owned restoration: {relative}")
    if relative.endswith(".png"):
        owned = hashlib.sha256(current).hexdigest() == cleanup["logo_sha256"]
    else:
        owned = str(cleanup["marker"]).encode("utf-8") in current
        # The product's recovery endpoint may replace a malformed locale
        # payload with exactly {}.  This exact two-byte state is produced by
        # this case's invalid-JSON branch and was observed before finalization.
        if relative == "locales/zh/custom.json" and current == b"{}":
            owned = True
    if not owned:
        raise RuntimeError(f"project-config file changed by another actor; refusing to overwrite: {relative}")
    mutate_project_config(target, original)
    mark_asset_state("project_config_snapshots", relative.replace("/", "_"), "DELETED")
