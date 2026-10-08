"""Portable orchestration primitives; runtime state always stays outside Git."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".next")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class BatchLock:
    """Use the original Daily lock name, including on Windows."""
    def __init__(self, path):
        self.path, self.handle = path, None

    def __enter__(self):
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
            raise RuntimeError("another daily run is active") from None
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()


def terminate_tree(process, group=True):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    elif group:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # Children can survive a parent that exits on SIGTERM.
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    process.wait(timeout=15)


def logged(command, cwd, env, log, timeout, *, new_session=True):
    """Bound each command and its children; never print env or argv secrets."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen([str(item) for item in command], cwd=cwd, env=env,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != "nt" and new_session)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_tree(process, group=new_session)
            return 124
        except BaseException:
            terminate_tree(process, group=new_session)
            raise


def fingerprint(repo):
    """Pin actual worktree bytes as well as HEAD, excluding generated runtime files."""
    ignored = {"node_modules", "__pycache__", ".pytest_cache", "test-results", "runs", ".playwright-internal"}
    digest = hashlib.sha256()
    for path in sorted((repo / "test-e2e").rglob("*")):
        relative = path.relative_to(repo)
        if not path.is_file() or set(relative.parts) & ignored:
            continue
        if path.suffix not in {".py", ".yaml", ".json", ".ts", ".tsx", ".mjs", ".ini", ".toml", ".txt", ".sh"}:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    product_diff = subprocess.check_output(["git", "-C", str(repo), "diff", "HEAD", "--", "backend", "sdk", "frontend", "deploy"])
    untracked = subprocess.check_output(["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard",
                                         "-z", "--", "backend", "sdk", "frontend", "deploy"])
    untracked_digest = hashlib.sha256()
    for raw in sorted(item for item in untracked.split(b"\0") if item):
        relative = os.fsdecode(raw)
        path = (repo / relative).resolve()
        if not path.is_relative_to(repo.resolve()):
            raise ValueError("Untracked product file escapes the checkout")
        untracked_digest.update(raw)
        untracked_digest.update(b"\0")
        untracked_digest.update(path.read_bytes())
    return {"head": head, "test_assets_sha256": digest.hexdigest(),
            "tracked_product_diff_sha256": hashlib.sha256(product_diff).hexdigest(),
            "untracked_product_sha256": untracked_digest.hexdigest()}


def config_fingerprint(home):
    """Pin operator configuration, excluding the refreshed anchor asset registry."""
    digest = hashlib.sha256()
    root = home / "config"
    for path in sorted(root.rglob("*")) if root.is_dir() else []:
        if path.is_symlink():
            raise ValueError("Machine config symlinks cannot be used for safe resume")
        if not path.is_file():
            continue
        # Per-case anchor preparation replaces this file with verified runtime IDs.
        # It is an output of the batch, not immutable operator configuration.
        if path.relative_to(root).as_posix() == "anchor-assets.yaml":
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def finalize(directory, plan, rows, error=None):
    """Account for every planned Case; interrupted work can never become PASS."""
    counts = Counter(row["case_id"] for row in rows)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    expected = {record["case_id"] for record in plan}
    unexpected = sorted(set(counts) - expected)
    for record in plan:
        if record["case_id"] not in counts:
            rows.append({"case_id": record["case_id"], "stage": record["stage"],
                         "result": "NOT_EXECUTED", "reason": error or "No terminal receipt", "evidence": []})
    summary_counts = dict(Counter(row["result"] for row in rows))
    by_id = {record["case_id"]: record for record in plan}
    for row in rows:
        record = by_id.get(row["case_id"], {})
        for key in ("feature_id", "title", "module", "owner"):
            if key in record:
                row.setdefault(key, record[key])
    incomplete = any(row["result"] in {"NOT_EXECUTED", "INTERRUPTED"} for row in rows)
    failures = any(row["result"] not in {"PASS", "RETIRED", "SKIPPED_BY_POLICY"} for row in rows)
    summary = {"schema_version": 1, "finished_at": now(), "planned": len(plan),
               "recorded": len(rows), "counts": summary_counts,
               "execution_complete": not (incomplete or error or duplicates or unexpected),
               "status": "INCOMPLETE" if incomplete or error or duplicates or unexpected else "FAILED" if failures else "PASSED",
               "error": error, "duplicate_case_ids": duplicates, "unexpected_case_ids": unexpected,
               "d6_complete": True}
    save(directory / "summary.json", summary)
    (directory / "checkpoints").mkdir(parents=True, exist_ok=True)
    (directory / "checkpoints/results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    render_report(directory, plan, rows, summary)
    return summary


def report_metrics(plan, rows):
    """Count planned identities once; duplicates or missing results are never passes."""
    by_id = {}
    for row in rows:
        by_id.setdefault(row["case_id"], []).append(row)
    stages = {}
    for record in plan:
        matches = by_id.get(record["case_id"], [])
        result = matches[0]["result"] if len(matches) == 1 else "INVALID_DUPLICATE" if matches else "NOT_EXECUTED"
        stages.setdefault(record["stage"], Counter())[result] += 1
    counts = sum(stages.values(), Counter())
    planned = len(plan)
    excluded = counts["RETIRED"] + counts["SKIPPED_BY_POLICY"]
    passed = counts["PASS"]
    return {"planned": planned, "passed": passed, "excluded": excluded,
            "overall_pass_rate": passed / planned * 100 if planned else None,
            "applicable_pass_rate": passed / (planned - excluded) * 100 if planned > excluded else None,
            "stages": stages}


def render_report(directory, plan, rows, summary):
    """Refresh the reading view only, preserving final receipts and batch timestamps."""
    metrics = report_metrics(plan, rows)
    def percent(value):
        return f"{value:.2f}%" if value is not None else "N/A"

    lines = ["# Nexent repository test report", "", f"Status: {summary['status']}",
             f"Cases: {summary['recorded']} / {summary['planned']}",
             f"Overall pass rate (PASS / planned): **{percent(metrics['overall_pass_rate'])}** "
             f"({metrics['passed']} / {metrics['planned']})",
             f"Applicable pass rate (excluding RETIRED and SKIPPED_BY_POLICY only): "
             f"**{percent(metrics['applicable_pass_rate'])}** "
             f"({metrics['passed']} / {metrics['planned'] - metrics['excluded']})",
             "Blocked, abnormal, cleanup-failed and unexecuted cases do not count as passes.",
             "", "| Result | Count |", "| --- | ---: |"]
    lines += [f"| {key} | {value} |" for key, value in sorted(summary["counts"].items())]
    lines += ["", "## Stage summary", "",
              "| Stage | Planned | PASS | Not passed | Retired / policy skipped | Overall pass rate |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for stage, counts in sorted(metrics["stages"].items()):
        total = sum(counts.values())
        excluded = counts["RETIRED"] + counts["SKIPPED_BY_POLICY"]
        lines.append(f"| {stage} | {total} | {counts['PASS']} | {total - counts['PASS'] - excluded} | "
                     f"{excluded} | {percent(counts['PASS'] / total * 100 if total else None)} |")
    def cell(value):
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>").replace("\r", "")

    unsuccessful = [row for row in rows if row["result"] not in {"PASS", "RETIRED", "SKIPPED_BY_POLICY"}]
    lines += ["", "## Case results — not passed only", "",
              "PASS, RETIRED and SKIPPED_BY_POLICY rows are omitted from this detail table. "
              "All results remain in checkpoints/results.jsonl and per-case evidence."]
    for stage in sorted(set(metrics["stages"]) | {row["stage"] for row in unsuccessful}):
        stage_rows = [row for row in unsuccessful if row["stage"] == stage]
        lines += ["", f"### {stage} — {len(stage_rows)} not passed", ""]
        if not stage_rows:
            lines += ["No non-passing cases in this stage."]
            continue
        lines += ["| Case | Stage | Title | Feature | Module | Owner | Result | Reason | Duration (s) | Executed at (UTC) | Cleanup | Local evidence |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        lines += ["| " + " | ".join(cell(value) for value in (
            row['case_id'], row['stage'], row.get('title'), row.get('feature_id'), row.get('module'),
            row.get('owner', 'Unassigned'), row['result'], row.get('reason'), row.get('duration_seconds'), row.get('executed_at'),
            row.get('cleanup_reason') or row.get('cleanup_exit_code'),
            ', '.join(row.get('evidence', [])))) + " |" for row in stage_rows]
    if not unsuccessful:
        lines += ["", "No non-passing cases."]
    if summary.get("error"):
        lines += ["", "Batch ended before completion. Inspect status.json and local logs."]
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
