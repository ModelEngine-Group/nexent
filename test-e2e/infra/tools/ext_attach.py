# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Attach cases to the pre-deployed ext-knowledge mock instance.

The suite NEVER starts or stops the mock's Compose stack (deployment and
teardown are explicit operator steps); attaching means validating a
batch-owned instance, taking a shared lock, resetting per-case state and
exporting the runner/product URLs. Design contract:

- Cases declare dependencies through ``required_mock_services`` (logical
  IDs). The machine-local ``config/ext-knowledge.yaml`` explicitly maps
  which logical services THIS instance serves; other providers (the
  controlled test-assets service, memory-provider, ...) are never
  redirected here implicitly.
- Identity: ``GET /_mock/identity`` must report the run_id / source_revision
  / build_manifest_sha256 configured locally. A foreign or unowned instance
  is never attached — and never reset.
- Exclusivity: a machine-local ``lock_directory`` shared across test-homes
  holds one lock file per normalized runner endpoint, so two runners cannot
  drive the same instance concurrently.
- Unknown cleanup state: a hard-killed worker cannot release its lock state;
  the next attach refuses until an operator confirms ownership and runs
  ``python ext_attach.py --test-home <home> recover`` (identity check, full
  reset, state cleared).
- Multi-profile cases (``profile_selection`` in execution.yaml) resolve
  their effective dependencies from a machine-local profile config, e.g.
  ``config/aidp-journey.yaml`` selecting mock or real_smoke for the AIDP
  journey; the selection is recorded into the case evidence and exported
  as ``NEXENT_TEST_SELECTED_PROFILE``.

Every dependency failure is recorded through shared.preparation_evidence
(the worker then reports BLOCKED / BLOCKED_BY_DEPENDENCY) — a missing
dependency is never a skip and never a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator

# Logical service IDs from the legacy schema enum; only these are attachable.
EXT_LOGICAL_SERVICES = ("knowledge-provider", "http-fixture", "model-provider")
CONFIG_NAME = "ext-knowledge.yaml"
SCHEMA_NAME = "ext-knowledge.schema.json"
IDENTITY_KEYS = ("run_id", "source_revision", "build_manifest_sha256")
ALL_HEALTH_SERVICES = (
    "datamate", "dify", "ragflow", "idata", "haotian", "assets", "fault", "aidp",
)
HTTP_TIMEOUT_SECONDS = 10.0


class AttachError(RuntimeError):
    """A dependency precondition failed; message is safe for reports."""


def _automation_path(repo: Path) -> Path:
    return repo / "test-e2e" / "infra" / "automation"


def _ensure_automation(repo: Path) -> None:
    path = str(_automation_path(repo))
    if path not in sys.path:
        sys.path.insert(0, path)


def _dependency_failure(case_id: str, detail: str):
    """Record a prerequisite-failure receipt and return the error to raise."""
    _ensure_automation(repo_root())
    from shared.asset_registry import AssetDependencyError
    from shared.preparation_evidence import record_failure

    error = AssetDependencyError(
        section="mock", key="ext-knowledge",
        consumer_case_id=case_id, detail=detail,
    )
    record_failure(error)
    return error


def _repo_root(configured: str | None = None) -> Path:
    if configured:
        root = Path(configured).resolve()
    else:
        root = Path(__file__).resolve().parents[3]
    if not (root / "test-e2e/infra/automation").is_dir():
        raise AttachError(f"{root} does not look like the Nexent checkout")
    return root


def repo_root(configured: str | None = None) -> Path:
    return _repo_root(configured)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def _check_root_url(value: str, field: str) -> None:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise AttachError(f"{field} must use http or https")
    if parts.username or parts.password:
        raise AttachError(f"{field} must not embed credentials")
    if any(character.isspace() for character in value):
        raise AttachError(f"{field} must not contain whitespace")
    if value.endswith("/"):
        raise AttachError(f"{field} must not end with a slash")
    if parts.path not in ("",):
        raise AttachError(f"{field} must be a pure root address (no service path)")
    if parts.query or parts.fragment:
        raise AttachError(f"{field} must not carry a query or fragment")
    if not parts.hostname:
        raise AttachError(f"{field} has no host")


def validate_config(payload, home: Path) -> None:
    """Schema plus root-address rules the JSON Schema cannot express."""
    for field in ("runner_url", "product_url"):
        _check_root_url(str(payload.get(field) or ""), field)
    # The two addresses MAY legitimately be equal: a host-mode product
    # deployment (backend running on the host, not in the compose network)
    # reaches the mock through the same published loopback port as the
    # runner. The helpers still keep the two calling sides explicit.
    lock_directory = Path(str(payload["lock_directory"]))
    if not lock_directory.is_absolute():
        raise AttachError("lock_directory must be an absolute machine-local path")
    if lock_directory == home or lock_directory.is_relative_to(home) or home.is_relative_to(lock_directory):
        # The lock must outlive and span test-homes, not sit inside one.
        raise AttachError("lock_directory must live outside the test-home")


def load_config(home: Path, repo: Path) -> dict:
    path = home / "config" / CONFIG_NAME
    if not path.is_file():
        raise AttachError(
            f"config/{CONFIG_NAME} is missing; cases declaring ext-served mock "
            "services cannot attach without it"
        )
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise AttachError(f"config/{CONFIG_NAME} is not valid YAML") from None
    if not isinstance(payload, dict):
        raise AttachError(f"config/{CONFIG_NAME} must contain a mapping")
    schema = json.loads(
        (repo / "test-e2e/infra/config" / SCHEMA_NAME).read_text(encoding="utf-8")
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=str)
    if errors:
        raise AttachError(
            f"config/{CONFIG_NAME} is invalid at " + ", ".join(str(list(error.path)) for error in errors)
        )
    validate_config(payload, home)
    return payload


def config_problems(home: Path, repo: Path) -> list[str]:
    """Preflight helper: shape problems when the config exists, else []."""
    if not (home / "config" / CONFIG_NAME).is_file():
        return []
    try:
        load_config(home, repo)
    except AttachError as exc:
        return [f"config/{CONFIG_NAME}: {exc}"]
    return []


# ---------------------------------------------------------------------------
# HTTP helpers (proxy-bypassed, stdlib only)
# ---------------------------------------------------------------------------

def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _reachable(url: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> bool:
    """Reachability in the local_preflight sense: any HTTP response below 500
    counts (service roots legitimately 404); only 5xx or no answer does not."""
    request = urllib.request.Request(url, headers={"User-Agent": "nexent-ext-attach"})
    try:
        with _opener().open(request, timeout=timeout) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _request(url: str, method: str = "GET", payload=None, timeout: float = HTTP_TIMEOUT_SECONDS):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "User-Agent": "nexent-ext-attach"},
    )
    try:
        with _opener().open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise AttachError(f"{method} {url} returned HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AttachError(f"{method} {url} failed: {type(exc).__name__}") from None


# ---------------------------------------------------------------------------
# locking and attach state
# ---------------------------------------------------------------------------

def endpoint_lock_paths(config: dict) -> tuple[Path, Path]:
    """(lock file, state file) for the configured runner endpoint.

    The endpoint is normalized (scheme://host:port, no path) so two configs
    that differ only in cosmetics share one lock. The directory is machine
    local and shared across test-homes by contract.
    """
    parts = urlsplit(str(config["runner_url"]))
    normalized = f"{parts.scheme}://{parts.netloc}"
    stem = f"ext-knowledge-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"
    directory = Path(str(config["lock_directory"]))
    return directory / f"{stem}.lock", directory / f"{stem}.state.json"


def _read_state(state_path: Path) -> dict | None:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_state(state_path: Path, run_id: str, case_id: str, released: bool) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({
            "run_id": run_id, "case_id": case_id, "released": released,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }, indent=2) + "\n",
        encoding="utf-8",
    )


class _FileLock:
    """Exclusive OS lock, Windows/POSIX, mirroring suite_runtime.BatchLock."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.path.stat().st_size == 0:
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise AttachError(
                "the ext-knowledge instance is locked by another runner "
                f"(lock file {self.path.name}); concurrent use is not supported"
            ) from None

    def release(self) -> None:
        if self.handle:
            self.handle.close()
            self.handle = None


# ---------------------------------------------------------------------------
# profile selection (multi-profile cases, e.g. the AIDP journey)
# ---------------------------------------------------------------------------

def _load_profile_config(home: Path, repo: Path, key: str, case_id: str) -> dict:
    config_path = home / "config" / f"{key}.yaml"
    if not config_path.is_file():
        raise _dependency_failure(
            case_id, f"profile selection config config/{key}.yaml is missing"
        )
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        raise _dependency_failure(case_id, f"config/{key}.yaml is not valid YAML") from None
    schema_path = repo / "test-e2e/infra/config" / f"{key}.schema.json"
    if schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=str)
        if errors:
            raise _dependency_failure(
                case_id, f"config/{key}.yaml is invalid at " + ", ".join(str(list(e.path)) for e in errors)
            )
    if not isinstance(payload, dict):
        raise _dependency_failure(case_id, f"config/{key}.yaml must contain a mapping")
    return payload


def resolve_profile_selection(repo: Path, home: Path, record: dict) -> dict | None:
    """Resolve a multi-profile case's selected profile and effective services.

    Returns None for single-profile cases (the plain required_mock_services
    path). Raises AssetDependencyError (after recording the receipt) when a
    declared profile selection cannot be resolved.
    """
    execution = record.get("execution") or {}
    key = execution.get("profile_selection")
    if not key:
        return None
    case_id = record["case_id"]
    declared = (execution.get("implementations") or [{}])[0].get("profiles") or []
    if len(declared) < 2:
        raise _dependency_failure(
            case_id, "profile_selection requires an implementation with multiple profiles"
        )
    payload = _load_profile_config(home, repo, str(key), case_id)
    selected = payload.get("selected_profile")
    if selected not in declared:
        raise _dependency_failure(
            case_id,
            f"config/{key}.yaml selects profile {selected!r} which the case does not declare ({sorted(declared)})",
        )
    case_path = repo / "test-e2e/cases" / case_id / "case.yaml"
    try:
        case_document = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        case_document = {}
    entries = ((case_document or {}).get("case", {}).get("execution") or {}).get("profiles") or []
    entry = next((item for item in entries if item.get("name") == selected), None)
    required = list(entry.get("required_services") or []) if entry else []
    return {
        "selection_key": str(key),
        "selected_profile": str(selected),
        "config": payload,
        "required_services": required,
    }


# ---------------------------------------------------------------------------
# attach context
# ---------------------------------------------------------------------------

class ExtKnowledgeAttach:
    """Per-case attach lifecycle; use from the suite worker only."""

    def __init__(self, repo: Path, home: Path, directory: Path, env: dict,
                 required_services, case_id: str, record: dict | None = None):
        self.repo = repo
        self.home = home
        self.directory = Path(directory)
        self.env = env
        self.required_services = list(required_services or [])
        self.case_id = case_id
        self.record = record or {}
        self.profile: dict | None = None
        self.config: dict | None = None
        self.attached = False
        self._identity: dict = {}
        self._instance_mutations = False
        self._lock: _FileLock | None = None
        self._lock_state_path: Path | None = None

    # -- lifecycle ---------------------------------------------------------

    def attach(self) -> None:
        """Validate and lock the instance; export case env; reset state.

        Raises AssetDependencyError (receipt recorded) on any dependency
        failure; the worker maps that to BLOCKED/BLOCKED_BY_DEPENDENCY.
        """
        self.profile = resolve_profile_selection(self.repo, self.home, self.record)
        if self.profile:
            self.env["NEXENT_TEST_SELECTED_PROFILE"] = self.profile["selected_profile"]
            required = self.profile["required_services"]
            self._export_profile_values(self.profile)
        else:
            required = self.required_services
        needed = [service for service in required if service in EXT_LOGICAL_SERVICES]
        if not needed:
            # Nothing this instance serves: no attach, no lock, no reset. The
            # selected profile (if any) is still recorded as case evidence.
            self._write_evidence({
                "attached": False,
                "selected_profile": self.profile["selected_profile"] if self.profile else None,
                "required_services": required,
            })
            return

        try:
            self._attach_locked(needed, required)
        except AttachError as exc:
            raise _dependency_failure(self.case_id, str(exc)) from None
        self.attached = True
        self._write_evidence({
            "attached": True,
            "selected_profile": self.profile["selected_profile"] if self.profile else None,
            "required_services": required,
            "served_services": needed,
            "identity": self._identity,
        })

    def _attach_locked(self, needed: list[str], required: list[str]) -> None:
        config = load_config(self.home, self.repo)
        self.config = config
        missing = [service for service in needed if service not in config["logical_services"]]
        if missing:
            raise AttachError(
                "the local ext-knowledge instance does not serve "
                f"{', '.join(missing)} (configured: {', '.join(config['logical_services'])})"
            )

        # Identity first: a foreign or unowned instance is never written to.
        status, identity = _request(f"{config['runner_url']}/_mock/identity")
        self._identity = identity
        if not identity.get("run_id"):
            raise AttachError(
                "the ext-knowledge instance reports no run_id (unowned); "
                "it was started without deployment metadata and must not be reset"
            )
        for key in IDENTITY_KEYS:
            if str(identity.get(key, "")) != str(config["owner_run_id" if key == "run_id" else key]):
                raise AttachError(
                    f"ext-knowledge identity mismatch for {key}: instance is foreign "
                    "(different deployment); refusing to attach or reset"
                )

        lock_path, state_path = endpoint_lock_paths(config)
        previous = _read_state(state_path)
        if previous and not previous.get("released"):
            raise AttachError(
                "previous attach state was not released cleanly "
                f"(run_id={previous.get('run_id')}, case={previous.get('case_id')}); "
                "confirm ownership and run: python test-e2e/infra/tools/ext_attach.py "
                f"--test-home {self.home} recover"
            )

        lock = _FileLock(lock_path)
        lock.acquire()
        self._lock = lock
        self._lock_state_path = state_path
        _write_state(state_path, str(config["owner_run_id"]), self.case_id, released=False)

        # Whether any instance-mutating call has been attempted. Attach-phase
        # failures before this point leave the instance untouched, so the
        # state file can be marked released; a failed reset means the
        # instance state is unknown and the next runner must be blocked.
        self._instance_mutations = False
        try:
            # Runner-side readiness: all eight route sets must be healthy.
            status, health = _request(f"{config['runner_url']}/health")
            services = health.get("services") or {}
            unhealthy = [name for name in ALL_HEALTH_SERVICES if services.get(name) != "ok"]
            if health.get("status") != "ok" or unhealthy:
                raise AttachError(
                    "ext-knowledge health check failed for: " + ", ".join(unhealthy or ["status"])
                )

            # Product-side readiness: the migrated consumers drive the live
            # product config and runtime services; an unreachable product
            # stack is a dependency failure, not a confusing test error.
            # Reachability follows the local_preflight semantics (a 404
            # service root is a live service).
            for env_name in ("NEXENT_CONFIG_URL", "NEXENT_RUNTIME_URL"):
                endpoint = self.env.get(env_name, "").rstrip("/")
                if not endpoint:
                    continue
                if not _reachable(endpoint):
                    raise AttachError(
                        f"the product service behind {env_name} is not reachable at {endpoint}"
                    )

            # Per-case baseline: full reset (route sets + AIDP data, failure
            # counters and knobs) and a clean wire log, so every case starts
            # from the seed contract.
            self._instance_mutations = True
            status, _ = _request(f"{config['runner_url']}/_reset", method="POST", payload={})
            if status != 200:
                raise AttachError(f"per-case reset failed with HTTP {status}")
            status, _ = _request(f"{config['runner_url']}/_wire-log/clear", method="POST", payload={})
        except AttachError:
            self._release_lock()
            if not self._instance_mutations and self._lock_state_path is not None:
                _write_state(self._lock_state_path, str(config["owner_run_id"]),
                             self.case_id, released=True)
            raise

        self.env["NEXENT_EXT_KNOWLEDGE_RUNNER_URL"] = str(config["runner_url"])
        self.env["NEXENT_EXT_KNOWLEDGE_PRODUCT_URL"] = str(config["product_url"])

    def _export_profile_values(self, profile: dict) -> None:
        """Export the selected profile's machine-local values for the script.

        The AIDP journey's real_smoke profile needs the real KB identity,
        retrieval query and oracle; the mock profile's oracle is fixed by
        the seed contract and needs no extra values.
        """
        if profile["selected_profile"] != "real_smoke":
            return
        values = profile["config"].get("real_smoke") or {}
        mapping = {
            "kb_id": "NEXENT_TEST_AIDP_REAL_KB_ID",
            "kb_name": "NEXENT_TEST_AIDP_REAL_KB_NAME",
            "doc_name": "NEXENT_TEST_AIDP_REAL_DOC_NAME",
            "query": "NEXENT_TEST_AIDP_REAL_QUERY",
            "expected_text": "NEXENT_TEST_AIDP_REAL_EXPECTED_TEXT",
            "expected_source": "NEXENT_TEST_AIDP_REAL_EXPECTED_SOURCE",
        }
        # doc_name is optional (the file-management view check); the rest are
        # required by the aidp-journey schema, so an empty value here means
        # the schema file and this mapping drifted apart.
        optional = {"doc_name"}
        for source, env_name in mapping.items():
            value = str(values.get(source) or "").strip()
            if not value:
                if source in optional:
                    continue
                raise _dependency_failure(
                    self.case_id,
                    f"config/{profile['selection_key']}.yaml real_smoke.{source} is required "
                    "for the real_smoke profile",
                )
            self.env[env_name] = value

    def collect_evidence(self) -> None:
        """Save wire/control evidence; best-effort, never masks the result."""
        if not self.attached or not self.config:
            return
        runtime = self.directory / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        base = str(self.config["runner_url"])
        try:
            _, wire = _request(f"{base}/_wire-log?limit=2000")
            lines = [json.dumps({
                "type": "wire-stats",
                "retained": wire.get("retained"),
                "dropped": wire.get("dropped"),
                "exported_records": len(wire.get("records") or []),
            })]
            lines.extend(json.dumps(record, ensure_ascii=False) for record in wire.get("records") or [])
            (runtime / "ext-knowledge-wire.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:
            (runtime / "ext-knowledge-wire.jsonl").write_text(
                json.dumps({"type": "export-failed", "error": type(exc).__name__}) + "\n",
                encoding="utf-8",
            )
        try:
            _, control = _request(f"{base}/_mock/state")
            (runtime / "ext-knowledge-control.json").write_text(
                json.dumps(control, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except Exception as exc:
            (runtime / "ext-knowledge-control.json").write_text(
                json.dumps({"export_failed": type(exc).__name__}) + "\n", encoding="utf-8"
            )

    def release(self) -> int:
        """Restore clean state and release the lock; 0 on success, 2 on failure."""
        if not self.attached or not self.config:
            return 0
        problems: list[str] = []
        base = str(self.config["runner_url"])
        try:
            status, _ = _request(f"{base}/_reset", method="POST", payload={})
            if status != 200:
                problems.append(f"release reset returned HTTP {status}")
            _request(f"{base}/_wire-log/clear", method="POST", payload={})
        except AttachError as exc:
            problems.append(str(exc))
        try:
            # Decide the final instance state BEFORE releasing the lock so a
            # concurrent attacher can never observe released=True between the
            # unlock and an "unknown state" rewrite. Failure details land in
            # the release evidence either way.
            if self._lock_state_path:
                _write_state(self._lock_state_path, str(self.config["owner_run_id"]),
                             self.case_id, released=not problems)
        finally:
            self._release_lock()
        if problems:
            runtime = self.directory / "runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "ext-knowledge-release.json").write_text(
                json.dumps({"problems": problems}, indent=2) + "\n", encoding="utf-8"
            )
            return 2
        return 0

    def _release_lock(self) -> None:
        if self._lock:
            self._lock.release()
            self._lock = None

    # -- evidence ----------------------------------------------------------

    def _write_evidence(self, payload: dict) -> None:
        runtime = self.directory / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        body = {
            "case_id": self.case_id,
            "config_fingerprint_source": CONFIG_NAME,
            **payload,
        }
        if self.config:
            body["runner_url"] = self.config["runner_url"]
            body["product_url"] = self.config["product_url"]
            body["logical_services"] = self.config["logical_services"]
        (runtime / "ext-knowledge-attach.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# operator CLI: status / recover (explicit, never run by the suite itself)
# ---------------------------------------------------------------------------

def _cli_paths(args) -> tuple[Path, Path]:
    repo = repo_root(args.repo)
    home = Path(args.test_home).resolve()
    return repo, home


def _recover(repo: Path, home: Path) -> int:
    config = load_config(home, repo)
    base = str(config["runner_url"])
    _, identity = _request(f"{base}/_mock/identity")
    if str(identity.get("run_id")) != str(config["owner_run_id"]):
        print("Refused: instance identity does not match this configuration; not recovering a foreign instance")
        return 1
    lock_path, state_path = endpoint_lock_paths(config)
    lock = _FileLock(lock_path)
    lock.acquire()
    try:
        status, _ = _request(f"{base}/_reset", method="POST", payload={})
        if status != 200:
            print(f"Refused: full reset returned HTTP {status}; instance left untouched")
            return 1
        _request(f"{base}/_wire-log/clear", method="POST", payload={})
        if state_path.exists():
            state_path.unlink()
    finally:
        lock.release()
    print("Recovered: identity verified, full reset applied, attach state cleared")
    return 0


def _status(repo: Path, home: Path) -> int:
    config_path = home / "config" / CONFIG_NAME
    if not config_path.is_file():
        print(json.dumps({"configured": False}, indent=2))
        return 0
    config = load_config(home, repo)
    lock_path, state_path = endpoint_lock_paths(config)
    report = {
        "configured": True,
        "runner_url": config["runner_url"],
        "lock_file": str(lock_path),
        "state": _read_state(state_path),
    }
    try:
        _, identity = _request(f"{str(config['runner_url'])}/_mock/identity")
        report["identity_matches"] = all(
            str(identity.get(key, "")) == str(config["owner_run_id" if key == "run_id" else key])
            for key in IDENTITY_KEYS
        )
        _, health = _request(f"{str(config['runner_url'])}/health")
        report["services"] = health.get("services")
    except AttachError as exc:
        report["reachable"] = False
        report["error"] = str(exc)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--repo", type=str, default=None)
    parser.add_argument("action", choices=("status", "recover"))
    args = parser.parse_args(argv)
    repo, home = _cli_paths(args)
    try:
        if args.action == "recover":
            return _recover(repo, home)
        return _status(repo, home)
    except AttachError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
