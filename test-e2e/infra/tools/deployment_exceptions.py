# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Small deployment exception catalog and recoverable, opt-in mode switching."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import uuid
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator

from local_preflight import env_file
from suite_runtime import BatchLock, finalize, fingerprint, now, render_report, save

CATALOG = "test-e2e/infra/config/deployment-exceptions.yaml"
MARKER = "state/deployment-exceptions/pending.json"


def checked_yaml(path, schema):
    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        result = {}
        for key, value in node.value:
            name = loader.construct_object(key)
            if name in result:
                raise ValueError("Duplicate key in " + path.name)
            result[name] = loader.construct_object(value)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    if list(Draft202012Validator(json.loads(schema.read_text(encoding="utf-8"))).iter_errors(value)):
        raise ValueError("Invalid deployment configuration: " + path.name)
    return value


def catalog(repo, records=None):
    path = repo / CATALOG
    if not path.exists():
        return {"profiles": {}, "cases": {}, "recovery_cases": []}
    value = checked_yaml(path, path.with_suffix(".schema.json"))
    if set(value["cases"].values()) - set(value["profiles"]):
        raise ValueError("Deployment exception references an unknown profile")
    if set(value["recovery_cases"]) & set(value["cases"]):
        raise ValueError("Local recovery cannot use deployment exception Cases")
    if records is not None:
        available = {record["case_id"] for record in records}
        missing = (set(value["cases"]) | set(value["recovery_cases"])) - available
        if missing:
            raise ValueError("Deployment exceptions reference unknown Case IDs: " + ", ".join(sorted(missing)))
    return value


def groups(records, rules):
    result = {}
    for record in records:
        # Inactive historical Cases never cause a deployment switch.
        profile = rules["cases"].get(record["case_id"], "local") if record["status"] == "active" else "local"
        result.setdefault(profile, []).append(record)
    return {key: result[key] for key in ["local", *rules["profiles"]] if key in result}


def enabled(repo, home):
    path = home / "config/deployment-switch.yaml"
    return path.exists() and checked_yaml(path, repo / "test-e2e/infra/config/deployment-switch.schema.json")["enabled"]


def assert_recovered(home):
    if (home / MARKER).exists():
        raise RuntimeError("Pending deployment-mode recovery; inspect state/deployment-exceptions/pending.json")


def mock_product_url(env):
    host = env.get("NEXENT_TEST_ASSETS_CONTAINER_HOST", "").strip()
    try:
        port = int(env.get("NEXENT_EXT_KNOWLEDGE_MOCK_PORT", "30090"))
    except ValueError:
        raise ValueError("Invalid controlled Mock port") from None
    url = f"http://{host}:{port}"
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        raise ValueError("Invalid controlled Mock host") from None
    if not host or any(c.isspace() for c in host) or any(c in host for c in "/?#@") or not 1 <= port <= 65535:
        raise ValueError("Configure a container-reachable controlled Mock host and port")
    if not parsed.hostname:
        raise ValueError("Invalid controlled Mock host")
    return url


def patch_env(content, updates):
    """Replace allowed settings without evaluating shell or rewriting unrelated bytes."""
    text = content.decode("utf-8")
    for key, value in updates.items():
        pattern = re.compile(r"^(?:export\s+)?" + re.escape(key) + r"=.*$", re.MULTILINE)
        if len(pattern.findall(text)) > 1:
            raise ValueError("Duplicate deployment environment key: " + key)
        replacement = key + "=" + value
        if pattern.search(text):
            text = pattern.sub(lambda _: replacement, text)
        else:
            text = text.rstrip("\n") + "\n" + replacement + "\n"
    return text.encode("utf-8")


def protected_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".switch-next")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def link_or_copy(source, destination):
    """Keep original evidence paths valid without duplicating binaries on one disk."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


class ModeSwitch:
    """Snapshot private config before mutation; leave a recovery marker on unsafe exit."""
    def __init__(self, repo, home, directory, settings, env, hook):
        self.repo, self.home, self.directory = repo, home, directory
        self.settings, self.env, self.hook = settings, env, hook
        self.paths = [repo / "deploy/env/.env", repo / "deploy/common/local-config.yaml",
                      repo / "deploy/docker/.env.generated", home / "config/environment.yaml"]
        self.backup = home / "runtime/deployment-switch-backups" / directory.name
        self.originals = {}
        self.baseline_values = {}
        self.switched = False

    def snapshot(self):
        assert_recovered(self.home)
        values, problems = env_file(self.paths[0])
        if problems or values.get("ENABLE_AIDP_KNOWLEDGE", "false").lower() not in {"false", "0", "no", "off"}:
            raise RuntimeError("Deployment campaign must start from the configured Local baseline")
        self.baseline_values = {key: value for key, value in values.items()
                                if key in {"ENABLE_AIDP_KNOWLEDGE", "MODEL_ENGINE_ENABLED", "AIDP_SERVER_URL",
                                           "AIDP_API_KEY", "AIDP_TENANT_ID"}}
        if not self.settings["hooks"].get("deploy") or not self.settings["hooks"].get("preflight"):
            raise RuntimeError("Mode switching requires explicit deploy and preflight hooks")
        self.backup.mkdir(parents=True, mode=0o700)
        metadata = []
        for index, path in enumerate(self.paths):
            if path.is_symlink():
                raise ValueError("Deployment configuration cannot be a symlink")
            content = path.read_bytes() if path.exists() else None
            self.originals[path] = content
            if content is not None:
                protected_write(self.backup / str(index), content)
            metadata.append({"path": str(path), "backup": str(index), "existed": content is not None,
                             "sha256": hashlib.sha256(content).hexdigest() if content is not None else None})
        save(self.backup / "index.json", {"files": metadata})
        save(self.home / MARKER, {"batch": str(self.directory), "backup": str(self.backup),
                                 "status": "PREPARED", "files": metadata})

    def apply(self, profile, updates):
        self.switched = True  # Set before the first write so any partial failure restores.
        original = self.originals[self.paths[0]]
        protected_write(self.paths[0], patch_env(original, updates))
        config = yaml.safe_load(self.originals[self.paths[-1]].decode("utf-8"))
        config.setdefault("features", {})["aidp_knowledge"] = updates.get("ENABLE_AIDP_KNOWLEDGE", "false") == "true"
        protected_write(self.paths[-1], yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode())
        self.hook("deploy", self.settings, self.repo, self.home, self.directory / profile, self.env)
        self.hook("preflight", self.settings, self.repo, self.home, self.directory / profile, self.env)
        self.verify(updates, profile)

    def verify(self, updates, label):
        """Prove runtime flags through product APIs, not only a rewritten env file."""
        base = self.env["NEXENT_CONFIG_URL"].rstrip("/")
        expected_aidp = updates.get("ENABLE_AIDP_KNOWLEDGE", "false") == "true"
        opener = build_opener(ProxyHandler({}))
        last = "unreachable"
        for _ in range(30):
            try:
                with opener.open(base + "/tenant_config/deployment_version", timeout=5) as response:
                    data = json.load(response)
                containers = json.loads(subprocess.check_output(
                    ["docker", "inspect", "nexent-config", "nexent-runtime", "nexent-web", "nexent-data-process"],
                    text=True, timeout=20))
                expected = {"ENABLE_AIDP_KNOWLEDGE": str(expected_aidp).lower(),
                            "MODEL_ENGINE_ENABLED": updates.get("MODEL_ENGINE_ENABLED",
                                                                 self.baseline_values.get("MODEL_ENGINE_ENABLED", "false"))}
                expected.update({key: value for key, value in updates.items()
                                 if key in {"AIDP_SERVER_URL", "AIDP_TENANT_ID", "AIDP_API_KEY"}})
                actual = [dict(item.split("=", 1) for item in container["Config"]["Env"] if "=" in item)
                          for container in containers]
                matched = all(all(values.get(key, "false" if key.endswith("ENABLED") or key == "ENABLE_AIDP_KNOWLEDGE"
                                                          else "") == value for key, value in expected.items())
                              for values in actual)
                if data.get("enable_aidp_knowledge") == expected_aidp and matched:
                    save(self.directory / label / "mode-verification.json", {
                        "aidp_enabled": expected_aidp, "modelengine_enabled": expected["MODEL_ENGINE_ENABLED"],
                        "containers_verified": [container["Name"] for container in containers], "verified_at": now()})
                    return
                last = "mode mismatch"
            except (OSError, ValueError, subprocess.SubprocessError):
                last = "unreachable"
            time.sleep(1)
        raise RuntimeError("Product deployment mode verification failed: " + last)

    def restore(self):
        for path, content in self.originals.items():
            if content is not None:
                protected_write(path, content)
            else:
                path.unlink(missing_ok=True)
        if self.switched:
            self.hook("deploy", self.settings, self.repo, self.home, self.directory / "restore-local", self.env)
            self.hook("preflight", self.settings, self.repo, self.home, self.directory / "restore-local", self.env)
        self.verify(self.baseline_values, "restore-local")
        # Deployment can re-render ignored files; restore their exact saved bytes afterwards.
        for path, content in self.originals.items():
            if content is not None:
                protected_write(path, content)
            else:
                path.unlink(missing_ok=True)
        save(self.directory / "restoration.json", {"status": "RESTORED", "at": now(), "backup": str(self.backup)})


def execute_campaign(repo, home, records, settings, *, daily, publish_latest, execute_one, all_records, hook, machine_env,
                     validation_report=None):
    """Run only selected exceptions, restore Local on failure, and finalize once."""
    from report_ownership import enrich

    rules = catalog(repo, all_records)
    selected = groups(records, rules)
    if not enabled(repo, home):
        raise RuntimeError("Deployment exceptions selected; explicitly enable config/deployment-switch.yaml")
    assert_recovered(home)
    directory = home / "runs/repository-daily" / ("deployment-" + now().replace(":", "") + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, mode=0o700)
    env = machine_env(home, repo)
    state = {"status": "RUNNING", "started_at": now(), "stages": {f"D{i}": "PENDING" for i in range(7)}}
    provenance = {**fingerprint(repo), "batch_mode": "daily" if daily else "run", "deployment_campaign": True}
    report_records, warnings = enrich(repo, records, provenance["head"])
    save(directory / "plan.json", {"cases": records})
    save(directory / "provenance.json", provenance)
    save(directory / "report-ownership.json", {
        "head": provenance["head"], "warnings": warnings, "cases": report_records})
    save(directory / "deployment-plan.json", {key: [r["case_id"] for r in group] for key, group in selected.items()})
    save(directory / "status.json", state)
    save(directory / "pipeline.json", settings)
    if validation_report is not None:
        save(directory / "asset-validation.json", validation_report)
    switch = ModeSwitch(repo, home, directory, settings, env, hook)
    rows, error, restoration_ok = [], None, False
    old_handler = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    print(f"Deployment campaign: {directory}", flush=True)

    def child(label, group, *, recovery=False):
        child_dir = directory / "profiles" / label
        seen = set()

        def record_result(row):
            if not recovery and row["case_id"] not in seen:
                case_id = row["case_id"]
                for section in ("cases", "logs"):
                    source = child_dir / section / (case_id if section == "cases" else case_id + ".log")
                    if source.exists():
                        destination = directory / section / source.name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if source.is_dir():
                            shutil.copytree(source, destination, copy_function=link_or_copy)
                        else:
                            link_or_copy(source, destination)
                row["deployment_profile"] = label
                rows.append(row)
                seen.add(case_id)
                with (directory / "results.journal.jsonl").open("a", encoding="utf-8") as out:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                save(directory / "progress.json", {"finished": len(rows), "planned": len(records), "profile": label,
                                                    "last_case": case_id})
                accounted = {item["case_id"] for item in rows}
                for stage in (f"D{i}" for i in range(1, 6)):
                    expected = {item["case_id"] for item in records if item["stage"] == stage}
                    state["stages"][stage] = ("COMPLETE" if expected <= accounted else
                                              "RUNNING" if row["stage"] == stage or expected & accounted else "PENDING")
                save(directory / "status.json", state)

        execute_one(repo, home, group, {**settings, "notify": False}, directory=child_dir, on_result=record_result)
        summary = json.loads((child_dir / "summary.json").read_text())
        results = [json.loads(line) for line in (child_dir / "checkpoints/results.jsonl").read_text().splitlines() if line]
        # Finalization can add NOT_EXECUTED rows after an interruption.
        for row in results:
            record_result(row)
        if not summary["execution_complete"] or (recovery and any(row["result"] != "PASS" for row in results)):
            raise RuntimeError("Incomplete or unsafe deployment group: " + label)
        if any(row["result"] in {"TIMEOUT", "CLEANUP_FAILED"} and row["stage"] == "D5" for row in results):
            raise RuntimeError("Deployment group needs environment safety review")

    try:
        # Also excludes other opted-in test homes operating on this checkout.
        with BatchLock(repo / ".git/nexent-e2e-deployment.lock"):
            switch.snapshot()
            try:
                state["stages"]["D0"] = "RUNNING"
                save(directory / "status.json", state)
                if daily:
                    if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip():
                        raise RuntimeError("Daily requires a clean committed checkout")
                    if not settings["hooks"].get("build"):
                        raise RuntimeError("Daily requires a build hook")
                    from static_assets import inventory
                    static_rows = inventory(home)
                    save(directory / "d0/static-assets.json", {"scope": "full", "assets": static_rows})
                    if any(row["destination"] != "READY" for row in static_rows):
                        raise RuntimeError("Daily static assets are missing or differ from the catalog")
                    hook("build", settings, repo, home, directory, env)
                    hook("deploy", settings, repo, home, directory, env)
                    hook("preflight", settings, repo, home, directory, env)
                switch.verify({}, "local")
                state["stages"]["D0"] = "COMPLETE"
                for label, group in selected.items():
                    current = fingerprint(repo)
                    if current != {key: provenance[key] for key in current}:
                        raise RuntimeError("Source changed during deployment campaign")
                    if label != "local":
                        updates = {key: value.format(mock_product_url=mock_product_url(env), mock_aidp_key="mock-aidp-key")
                                   for key, value in rules["profiles"][label]["environment"].items()}
                        switch.apply(label, updates)
                    state["profile"] = label
                    save(directory / "status.json", state)
                    child(label, group)
            finally:
                state["profile"] = "restore-local"
                save(directory / "status.json", state)
                switch.restore()
                recovery = [r for r in all_records if r["case_id"] in rules["recovery_cases"]]
                child("restore-local", recovery, recovery=True)
                restoration_ok = True
                (home / MARKER).unlink(missing_ok=True)
                current = fingerprint(repo)
                if current != {key: provenance[key] for key in current}:
                    raise RuntimeError("Source changed before campaign finalization")
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
    finally:
        signal.signal(signal.SIGTERM, old_handler)
        summary = finalize(directory, report_records, rows, error)
        state.update(status=summary["status"], finished_at=now(), error=error, local_restored_and_verified=restoration_ok)
        state["stages"] = {f"D{i}": "COMPLETE" if summary["execution_complete"] else "INTERRUPTED" for i in range(7)}
        state["stages"]["D6"] = "COMPLETE"
        save(directory / "status.json", state)
        render_report(directory, report_records, rows, summary)
        save(home / "reports/repository-latest.json", {"batch": str(directory), "status": summary["status"]})
    if daily and summary["execution_complete"] and restoration_ok:
        if publish_latest:
            from suite_publish import publish_latest as publish
            try:
                publication = publish(directory, home, env)
            except Exception as exc:
                publication = {"status": "FAILED", "batch_id": directory.name, "error_type": type(exc).__name__}
                save(home / "state/report-publications" / directory.name / "receipt.json", publication)
            render_report(directory, report_records, rows, summary, sharing=publication)
        if settings.get("notify"):
            from suite_notify import send_report
            send_report(directory, env)
    return 0 if summary["status"] == "PASSED" else 1
