"""Publish a complete Daily reading bundle; never execute tests or send messages."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import quote
import zipfile

import yaml

from suite_runtime import BatchLock, now, render_report, save

SECRET_KEY = re.compile(r"password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|app[_-]?key|jwt", re.I)
CASE_FILES = frozenset({"receipt.json", "status.json", "acceptance-execution.json", "junit.xml",
                        "results.jsonl", "failure.json", "assertions.json", "events.jsonl",
                        "failure-network.jsonl", "cleanup-results.jsonl", "asset-journal.jsonl",
                        "test-assets-wire.jsonl", "error-context.md"})
TERMINAL_RESULTS = frozenset({"PASS", "FAIL", "BLOCKED", "AUTOMATION_ERROR", "RETIRED",
                              "SKIPPED_BY_POLICY", "CLEANUP_FAILED", "BLOCKED_BY_DEPENDENCY",
                              "EXECUTION_FAILED", "TIMEOUT"})
MANAGED_FILES = ("latest-batch.zip", "latest-report.md")


def secret_values(home, env):
    """Collect existing credentials for redaction without exporting new settings."""
    values = set()

    def collect(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                collect(item, str(name))
        elif isinstance(value, list):
            for item in value:
                collect(item, key)
        elif isinstance(value, str) and SECRET_KEY.search(key) and len(value) >= 4:
            values.add(value)

    collect(env)
    for path in sorted((home / "config").glob("*")):
        if path.is_symlink():
            raise ValueError("Cannot safely read symlinked redaction configuration")
        if not path.is_file():
            continue
        if path.suffix in {".yaml", ".yml"}:
            collect(yaml.safe_load(path.read_text(encoding="utf-8")))
        elif path.suffix == ".env":
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.strip())
                if match:
                    collect(match[2].strip().strip("\"'"), match[1])
    return sorted({variant for value in values for variant in
                   (value, html.escape(value), quote(value, safe=""), json.dumps(value)[1:-1])}, key=len, reverse=True)


def redact_text(text, secrets):
    """Keep complete diagnostic text, masking configured and protocol credentials."""
    for secret in secrets:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9_.~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED JWT]", text)
    text = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED]@", text)
    names = r"authorization|proxy-authorization|cookie|set-cookie|password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|app[_-]?key"
    text = re.sub(r"(?i)((?:[\"']?)(?:" + names + r")(?:[\"']?)\s*[:=]\s*)([\"'])(.*?)(\2)",
                  lambda match: match[1] + match[2] + "[REDACTED]" + match[2], text)
    text = re.sub(r"(?im)(\b(?:" + names + r")\s*[:=]\s*)([^\r\n]+)",
                  lambda match: match[1] + "[REDACTED]", text)
    return text


def redact_value(value, secrets):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SECRET_KEY.search(str(key)) else redact_value(item, secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    return redact_text(value, secrets) if isinstance(value, str) else value


def sanitized_bytes(path, secrets):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return (json.dumps(redact_value(json.loads(text), secrets), ensure_ascii=False, indent=2) + "\n").encode()
    if path.suffix == ".jsonl":
        output = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                output.append(json.dumps(redact_value(json.loads(line), secrets), ensure_ascii=False))
            except ValueError:
                # Interrupted diagnostic streams can end in a partial line.
                output.append(redact_text(line, secrets))
        return ("\n".join(output) + "\n").encode()
    return redact_text(text, secrets).encode()


def batch_data(batch, home):
    expected_root = home / "runs/repository-daily"
    if batch.is_symlink() or (home / "runs").is_symlink() or expected_root.is_symlink() or \
            not batch.resolve().is_relative_to(expected_root.resolve()):
        raise ValueError("Publication source must be an owned repository Daily batch")
    def read(name):
        path = batch / name
        if path.is_symlink():
            raise ValueError("Publication snapshots cannot be symlinks")
        return json.loads(path.read_text(encoding="utf-8"))
    summary, state, provenance = read("summary.json"), read("status.json"), read("provenance.json")
    plan = read("plan.json")["cases"]
    if not summary.get("execution_complete") or not summary.get("d6_complete"):
        raise ValueError("Publication requires a complete D6 and execution plan")
    if provenance.get("batch_mode") != "daily" or any(state.get("stages", {}).get(f"D{i}") != "COMPLETE" for i in range(7)):
        raise ValueError("Publication requires all Daily stages to be complete")
    checkpoint = batch / "checkpoints/results.jsonl"
    if checkpoint.is_symlink():
        raise ValueError("Publication checkpoint cannot be a symlink")
    rows = [json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected, actual = Counter(record["case_id"] for record in plan), Counter(row["case_id"] for row in rows)
    if expected != actual or any(count != 1 for count in expected.values()):
        raise ValueError("Publication case identities are incomplete or duplicated")
    if summary.get("planned") != len(plan) or summary.get("recorded") != len(rows) or \
            dict(Counter(row["result"] for row in rows)) != summary.get("counts") or \
            any(row["result"] not in TERMINAL_RESULTS for row in rows):
        raise ValueError("Publication counts or terminal results disagree with original receipts")
    for record in plan:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", record["case_id"]):
            raise ValueError("Unsafe Case identity in publication plan")
    return summary, state, provenance, plan, rows


def selected_files(batch, rows):
    """Select evidence, not entire runtime/config/data directories."""
    selected, excluded = [], []
    outcomes = {row["case_id"]: row["result"] for row in rows}
    for path in sorted(batch.rglob("*")):
        relative = path.relative_to(batch)
        if path.is_symlink():
            raise ValueError("Symlinked publication evidence is not allowed")
        if not path.is_file():
            continue
        parts = relative.parts
        allowed = parts[0] == "logs" and path.suffix == ".log" and path.name != "notification.log"
        allowed |= relative.as_posix() == "d0/static-assets.json"
        if len(parts) >= 3 and parts[0] == "cases" and parts[1] in outcomes:
            outcome = outcomes[parts[1]]
            if path.suffix in {".png", ".jpg", ".jpeg", ".webp", ".zip", ".webm", ".mp4"}:
                if outcome not in {"PASS", "RETIRED", "SKIPPED_BY_POLICY"}:
                    excluded.append({"path": relative.as_posix(), "reason": "Binary evidence has no privacy review; retained on execution host"})
                continue
            allowed = path.suffix == ".log" or path.name in CASE_FILES
            if any(part in {"agent-input", ".playwright-internal", "config", "assets"} for part in parts):
                allowed = False
                if path.name == "error-context.md" and outcome not in {"PASS", "RETIRED", "SKIPPED_BY_POLICY"}:
                    allowed = True
        if allowed:
            selected.append(path)
    return selected, excluded


def replace_pair(staging, destination):
    """Rollback local replacement failures; peers still receive files independently."""
    old = {}
    for name in MANAGED_FILES:
        target = destination / name
        if target.exists():
            backup = staging / (name + ".previous")
            shutil.copyfile(target, backup)
            old[name] = backup
    replaced = []
    try:
        for name in MANAGED_FILES:
            os.replace(staging / name, destination / name)
            replaced.append(name)
    except BaseException:
        for name in reversed(replaced):
            if name in old:
                os.replace(old[name], destination / name)
            else:
                (destination / name).unlink()
        raise


def publish_latest(batch, home, env=None, *, ownership_file=None):
    """Publish only named outputs; never alter the source batch or notify."""
    batch, home = Path(batch), Path(home).resolve()
    summary, state, provenance, plan, rows = batch_data(batch, home)
    ownership_path = Path(ownership_file) if ownership_file else batch / "report-ownership.json"
    ownership = json.loads(ownership_path.read_text(encoding="utf-8")) if ownership_path.exists() else {
        "head": provenance["head"], "warnings": ["No frozen ownership metadata in historical batch"], "cases": []}
    if ownership.get("head") != provenance.get("head"):
        raise ValueError("Ownership metadata belongs to a different batch revision")
    mapping = {record["case_id"]: record for record in ownership.get("cases", [])}
    if mapping and (set(mapping) != {row["case_id"] for row in rows} or len(mapping) != len(ownership["cases"])):
        raise ValueError("Ownership metadata does not match the publication plan")
    rows = [{**row, **{key: item for key, item in mapping.get(row["case_id"], {}).items()
                      if key in {"git_last_modifier", "responsibility"}}} for row in rows]
    secrets = secret_values(home, env or {})
    selected, excluded = selected_files(batch, rows)
    destination = home / "runs-ubuntu"
    if destination.is_symlink():
        raise ValueError("Publication directory cannot be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    for path in destination.iterdir():
        if path.name not in (*MANAGED_FILES, ".stfolder", ".stignore") or path.is_symlink():
            raise ValueError("Unexpected existing publication files; refusing to delete or overwrite them")
    staging_root = home / "state/report-publish-staging"
    if (home / "state").is_symlink() or staging_root.is_symlink():
        raise ValueError("Publication staging directory cannot be a symlink")
    staging_root.mkdir(parents=True, exist_ok=True)
    if destination.stat().st_dev != staging_root.stat().st_dev:
        raise ValueError("Publication staging and destination must share a filesystem")
    with BatchLock(home / "state/report-publish.lock"), tempfile.TemporaryDirectory(dir=staging_root) as temporary:
        staging = Path(temporary)
        sharing = {"status": "PUBLISHED", "batch_id": batch.name,
                   "excluded_binary_count": len(excluded), "published_at": now()}
        render_report(staging, plan, rows, summary, metadata_directory=batch,
                      evidence_root=batch.resolve().as_posix(), sharing=sharing)
        contents = {"report.md": redact_text((staging / "report.md").read_text(encoding="utf-8"), secrets).encode()}
        for name, value in (("summary.json", summary), ("status.json", state), ("provenance.json", provenance),
                            ("report-ownership.json", ownership), ("excluded-evidence.json", excluded)):
            contents[name] = (json.dumps(redact_value(value, secrets), ensure_ascii=False, indent=2) + "\n").encode()
        contents["checkpoints/results.jsonl"] = "".join(json.dumps(redact_value(row, secrets), ensure_ascii=False) + "\n" for row in rows).encode()
        exported_summary = json.loads(contents["summary.json"])
        exported_rows = [json.loads(line) for line in contents["checkpoints/results.jsonl"].decode().splitlines()]
        if exported_summary["counts"] != summary["counts"] or \
                [(row["case_id"], row["stage"], row["result"]) for row in exported_rows] != \
                [(row["case_id"], row["stage"], row["result"]) for row in rows] or \
                json.loads(contents["provenance.json"])["head"] != provenance["head"]:
            raise ValueError("Credential redaction conflicts with immutable result identities")
        for path in selected:
            contents[path.relative_to(batch).as_posix()] = sanitized_bytes(path, secrets)
        manifest = {"schema_version": 1, "batch_id": batch.name, "head": provenance["head"],
                    "published_at": sharing["published_at"], "counts": summary["counts"],
                    "privacy_policy": "Text allowlist with redaction; unreviewed binary evidence stays on execution host",
                    "excluded_binary_count": len(excluded),
                    "files": [{"path": name, "size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                              for name, value in sorted(contents.items())]}
        contents["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
        archive = staging / "latest-batch.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for name, value in contents.items():
                package.writestr(name, value)
        with zipfile.ZipFile(archive) as package:
            if package.testzip() is not None or set(package.namelist()) != set(contents):
                raise ValueError("Publication archive integrity check failed")
            for item in manifest["files"]:
                if hashlib.sha256(package.read(item["path"])).hexdigest() != item["sha256"]:
                    raise ValueError("Publication archive manifest check failed")
        (staging / "latest-report.md").write_bytes(contents["report.md"])
        if os.name != "nt":
            for name in MANAGED_FILES:
                (staging / name).chmod(0o640)
        sharing.update(archive_bytes=archive.stat().st_size, file_count=len(contents),
                       archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                       source_batch=str(batch.resolve()), source_head=provenance["head"])
        replace_pair(staging, destination)
        try:
            save(home / "state/report-publications" / batch.name / "receipt.json", sharing)
        except OSError:
            # The validated package manifest remains an audit even if local receipt storage fails.
            sharing["audit_warning"] = "Published package, but local publication receipt could not be saved"
        return sharing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--ownership-file", type=Path)
    args = parser.parse_args(argv)
    try:
        sharing = publish_latest(args.batch, args.test_home, os.environ, ownership_file=args.ownership_file)
    except Exception as exc:
        # Do not echo file contents, credentials, or arbitrary exception values.
        print("Publication failed: " + type(exc).__name__)
        return 2
    print(json.dumps(sharing, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
