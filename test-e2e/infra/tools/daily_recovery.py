# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Restore validated Local configuration while keeping failed deployment evidence."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re

import yaml

from local_preflight import env_file
from recovery_io import protected_write
from suite_runtime import BatchLock, deployment_lock_owned, now, save

MODE_MARKER = "state/deployment-exceptions/pending.json"
FAULT_MARKER = "state/deployment-guard/pending.json"
_RETRY = ContextVar("daily_deployment_retry", default=None)
MODE_KEYS = {"ENABLE_AIDP_KNOWLEDGE", "MODEL_ENGINE_ENABLED", "AIDP_SERVER_URL", "AIDP_API_KEY", "AIDP_TENANT_ID"}


def configuration_paths(repo, home):
    return [repo / "deploy/env/.env", repo / "deploy/common/local-config.yaml",
            repo / "deploy/docker/.env.generated", home / "config/environment.yaml"]


def plain(path):
    """Reject symlinks/junctions, including ancestors, before reading or replacing files."""
    if path.is_symlink() or os.path.normcase(str(path.resolve())) != os.path.normcase(str(path.absolute())):
        raise RuntimeError("Recovery paths must not contain symbolic links")
    return path


def document(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate recovery key")
            result[key] = value
        return result
    try:
        return json.loads(plain(path).read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, ValueError):
        raise RuntimeError("Recovery journal or index is missing or invalid") from None


def owner_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise RuntimeError("Recovery owner PID is invalid")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is not proof of exit.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def current_retry(home):
    retry = _RETRY.get()
    return retry if retry is not None and retry.home == home.resolve() and deployment_lock_owned(retry.repo) else None


def pending_retry_allowed(home):
    retry = current_retry(home)
    return retry is not None and retry.marker_digest == hashlib.sha256(plain(retry.marker).read_bytes()).hexdigest()


class DailyRetry:
    def __init__(self, repo, home, directory):
        self.repo, self.home = repo.resolve(), home.resolve()
        self.marker = self.home / MODE_MARKER
        self.marker_bytes = plain(self.marker).read_bytes()
        self.marker_digest = hashlib.sha256(self.marker_bytes).hexdigest()
        self.payload = document(self.marker)
        self.archive = self.home / "runtime/daily-recovery" / directory.name
        self.receipt = directory / "recovery.json"
        self.originals = self.validate()

    def validate(self):
        value = self.payload
        if not isinstance(value, dict) or value.get("status") not in {"PREPARED", "RESTORE_FAILED"}:
            raise RuntimeError("Unsupported deployment recovery state")
        try:
            batch, backup = Path(value["batch"]), Path(value["backup"])
            files = value["files"]
            if (not batch.is_absolute() or not backup.is_absolute()
                    or plain(batch).parent != self.home / "runs/repository-daily"
                    or plain(backup) != self.home / "runtime/deployment-switch-backups" / batch.name):
                raise ValueError("unowned recovery paths")
            if "owner_pid" in value:
                if owner_alive(value["owner_pid"]):
                    raise RuntimeError("Previous deployment owner is still active")
            previous = document(batch / "status.json")
            if previous.get("status") not in {"INCOMPLETE", "FAILED", "PASSED", "COMPLETE"}:
                raise RuntimeError("Deployment journal has no terminal owner evidence")
            journal = next((p for p in (batch / "checkpoints/results.jsonl", batch / "results.journal.jsonl")
                            if p.exists() or p.is_symlink()), None)
            if journal is not None:
                for line in plain(journal).read_text(encoding="utf-8").splitlines():
                    if not isinstance(json.loads(line), dict):
                        raise ValueError("Invalid previous execution journal")
            elif previous.get("stages", {}).get("D5", "PENDING") != "PENDING":
                raise RuntimeError("Previous D5 execution has no recovery evidence")
            if not isinstance(files, list) or len(files) != 4 or document(backup / "index.json") != {"files": files}:
                raise ValueError("incomplete backup index")
            originals = {}
            for index, path in enumerate(configuration_paths(self.repo, self.home)):
                plain(path)
                item = files[index]
                if (not isinstance(item, dict) or item.get("path") != str(path) or item.get("backup") != str(index)
                        or type(item.get("existed")) is not bool):
                    raise ValueError("unexpected backup target")
                content = None
                if item["existed"]:
                    content = plain(backup / str(index)).read_bytes()
                    if not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")) or hashlib.sha256(content).hexdigest() != item["sha256"]:
                        raise ValueError("backup checksum mismatch")
                elif item.get("sha256") is not None:
                    raise ValueError("invalid absent backup")
                originals[path] = content
            env_path, *_, config_path = originals
            if originals[env_path] is None or originals[config_path] is None:
                raise ValueError("Local baseline is missing")
            baseline, problems = env_file(backup / "0")
            if problems or baseline.get("ENABLE_AIDP_KNOWLEDGE", "false").lower() not in {"false", "0", "no", "off"}:
                raise ValueError("backup is not a Local baseline")
            current, problems = env_file(env_path)
            if problems or {k: v for k, v in current.items() if k not in MODE_KEYS} != {k: v for k, v in baseline.items() if k not in MODE_KEYS}:
                raise ValueError("unrelated deployment settings changed")
            config = yaml.safe_load(originals[config_path])
            current_config = yaml.safe_load(config_path.read_bytes())
            for candidate in (config, current_config):
                features = candidate.setdefault("features", {})
                if not isinstance(features, dict):
                    raise ValueError("invalid environment features")
            if config["features"].get("aidp_knowledge", False) is not False:
                raise ValueError("environment backup is not Local")
            config["features"].pop("aidp_knowledge", None)
            current_config["features"].pop("aidp_knowledge", None)
            if config != current_config:
                raise ValueError("unrelated environment settings changed")
            return originals
        except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
            raise RuntimeError("Deployment recovery backup/configuration failed safety validation") from None

    def prepare(self):
        plain(self.archive)
        self.archive.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.archive.mkdir(mode=0o700)
        protected_write(self.archive / "pending.json", self.marker_bytes)
        # Preserve every current file before the first configuration write.
        before_images = {}
        for index, path in enumerate(self.originals):
            if path.exists():
                content = path.read_bytes()
                protected_write(self.archive / str(index), content)
                before_images[str(index)] = hashlib.sha256(content).hexdigest()
            else:
                before_images[str(index)] = None
        self.record("PREPARED_FOR_REDEPLOY", before_images=before_images)
        for path, content in self.originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                protected_write(path, content)

    def resume_prepared(self):
        """Revalidate the supervisor's before-images without writing a second backup."""
        receipt = document(self.receipt)
        if (receipt.get("status") != "PREPARED_FOR_REDEPLOY"
                or receipt.get("evidence_backup") != str(self.archive)
                or receipt.get("previous_batch") != self.payload["batch"]
                or plain(self.archive / "pending.json").read_bytes() != self.marker_bytes):
            raise RuntimeError("Prepared Daily recovery receipt differs from its journal")
        before_images = receipt.get("before_images")
        if not isinstance(before_images, dict) or set(before_images) != {str(i) for i in range(len(self.originals))}:
            raise RuntimeError("Prepared Daily recovery before-image index is incomplete")
        for index, digest in before_images.items():
            path = plain(self.archive / index)
            if digest is None:
                if path.exists():
                    raise RuntimeError("Unexpected prepared recovery before-image")
            elif (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                  or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise RuntimeError("Prepared recovery before-image checksum differs")
        for path, content in self.originals.items():
            actual = plain(path).read_bytes() if path.exists() else None
            if actual != content:
                raise RuntimeError("Prepared Local configuration changed before execution")

    def record(self, status, **details):
        save(self.receipt, {"status": status, "at": now(), "previous_batch": self.payload["batch"],
                            "evidence_backup": str(self.archive), **details})


@contextmanager
def prepare_daily_retry(repo, home, directory, *, prepared=False):
    """Require the checkout lease; retain the marker until a verified new campaign owns it."""
    if not deployment_lock_owned(repo):
        raise RuntimeError("Daily recovery requires the checkout deployment lock")
    # A surviving D5 child can retain this lease after its launcher has exited.
    with BatchLock(home / "state/deployment-guard/exclusive.lock"):
        if (home / FAULT_MARKER).exists() or (home / FAULT_MARKER).is_symlink():
            raise RuntimeError("Pending D5 fault recovery needs container/data safety review before synchronization")
    retry = DailyRetry(repo, home, directory) if (home / MODE_MARKER).exists() or (home / MODE_MARKER).is_symlink() else None
    if retry is None and prepared and (directory / "recovery.json").exists():
        if document(directory / "recovery.json").get("status") == "PREPARED_FOR_REDEPLOY":
            raise RuntimeError("Prepared Daily recovery journal disappeared before execution")
    if retry is not None:
        retry.resume_prepared() if prepared else retry.prepare()
    token = _RETRY.set(retry)
    try:
        yield retry
    finally:
        _RETRY.reset(token)
