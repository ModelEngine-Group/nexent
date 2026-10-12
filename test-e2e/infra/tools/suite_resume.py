"""Fail-closed continuation of an interrupted, case-local developer batch."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from static_assets import inventory as static_inventory
from suite_runtime import config_fingerprint, fingerprint


SAFE_RESULTS = {"PASS", "FAIL", "BLOCKED", "EXECUTION_FAILED", "RETIRED", "SKIPPED_BY_POLICY"}
PROVENANCE_KEYS = ("head", "test_assets_sha256", "tracked_product_diff_sha256", "untracked_product_sha256")


def read_json(path: Path):
    if not path.is_file():
        raise ValueError(f"Cannot resume: missing {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot resume: invalid {path.name}") from exc


def read_journal(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Cannot resume: invalid journal row {number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Cannot resume: invalid journal row {number}")
        rows.append(row)
    return rows


def prepare_resume(repo: Path, home: Path, source: Path, settings: dict,
                   registry_records: list[dict]) -> dict:
    """Return a read-only resume plan; never infer a PASS from an incomplete report."""
    root = (home / "runs/repository-daily").resolve()
    if source.is_symlink() or source.resolve().parent != root or not source.is_dir():
        raise ValueError("Resume source must be one existing direct child of the local batch root")
    source = source.resolve()
    if (source / "resume-child.json").exists():
        raise ValueError("This batch already has a resume child; continue that child instead")
    summary = read_json(source / "summary.json")
    status = read_json(source / "status.json")
    if (summary.get("status") != "INCOMPLETE" or summary.get("execution_complete") is not False or
            summary.get("error") != "Interrupted" or status.get("status") != "INCOMPLETE"):
        raise ValueError("Only a cleanly finalized interrupted batch can resume automatically")
    if status.get("stages", {}).get("D0") != "COMPLETE":
        raise ValueError("D0 did not complete; start a fresh batch instead")
    if (source / "notification.json").exists():
        raise ValueError("A batch with notification state cannot resume automatically")
    provenance = read_json(source / "provenance.json")
    if provenance.get("batch_mode") != "run":
        raise ValueError("Automatic resume currently supports local run batches only")
    actual = fingerprint(repo)
    if any(provenance.get(key) != actual.get(key) for key in PROVENANCE_KEYS):
        raise ValueError("Product HEAD or test asset bytes differ from the interrupted batch")
    if provenance.get("config_sha256") != config_fingerprint(home):
        raise ValueError("Machine-local config differs from the interrupted batch")
    if read_json(source / "pipeline.json") != settings:
        raise ValueError("Pipeline settings differ from the interrupted batch")
    plan = read_json(source / "plan.json")
    records = plan.get("cases") if isinstance(plan, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError("Cannot resume: invalid saved Case plan")
    if len({record.get("case_id") for record in records}) != len(records):
        raise ValueError("Cannot resume: duplicate Case IDs in saved plan")
    catalog = {record["case_id"]: record for record in registry_records}
    if any(catalog.get(record.get("case_id")) != record for record in records):
        raise ValueError("Current Case bindings differ from the interrupted plan")
    static_rows = static_inventory(home, selected=None if provenance.get("full_static_assets") else
                                   set(provenance.get("required_static_assets", [])))
    if any(row["destination"] != "READY" for row in static_rows):
        raise ValueError("Required static assets changed or are missing")

    journal = read_journal(source / "results.journal.jsonl")
    if len(journal) > len(records):
        raise ValueError("Cannot resume: journal exceeds the saved Case plan")
    expected_counts = {name: count for name, count in summary.get("counts", {}).items() if name != "NOT_EXECUTED"}
    if dict(Counter(row.get("result") for row in journal)) != expected_counts:
        raise ValueError("Cannot resume: summary and completed journal disagree")
    completed = set()
    reused = []
    for index, row in enumerate(journal):
        record = records[index]
        case_id = record["case_id"]
        if row.get("case_id") != case_id or row.get("stage") != record["stage"]:
            raise ValueError("Cannot resume: journal is not a contiguous plan prefix")
        if row.get("result") not in SAFE_RESULTS:
            raise ValueError(f"Cannot resume: {case_id} has an unsafe previous result")
        if record["status"] == "active" and record.get("execution"):
            receipt = read_json(source / "cases" / case_id / "receipt.json")
            if (receipt.get("case_id") != case_id or receipt.get("stage") != record["stage"] or
                    receipt.get("result") != row["result"] or receipt.get("cleanup_exit_code") != 0):
                raise ValueError(f"Cannot resume: {case_id} lacks a matching clean receipt")
            runtime = source / "cases" / case_id / "runtime"
            if (runtime / "resolved-assets.yaml").exists() and not (runtime / "cleanup-results.jsonl").is_file():
                raise ValueError(f"Cannot resume: {case_id} has unverified asset cleanup")
        completed.add(case_id)
        evidence = []
        for item in row.get("evidence", []):
            path = Path(item)
            origin = Path(row.get("reused_from", source)).resolve()
            if origin.parent != root or not origin.is_dir():
                raise ValueError("Cannot resume: reused evidence source is invalid")
            resolved = path.resolve() if path.is_absolute() else (source / path).resolve()
            if not resolved.is_relative_to(origin):
                raise ValueError("Cannot resume: evidence path escapes the source batch")
            if not resolved.exists():
                raise ValueError(f"Cannot resume: {case_id} evidence is missing")
            evidence.append(str(resolved))
        reused.append({**row, "evidence": evidence, "reused_from": str(source)})
    case_root = source / "cases"
    if case_root.exists() and any(path.name not in completed for path in case_root.iterdir()):
        raise ValueError("An unrecorded Case may have created assets; verify cleanup before retry")
    if len(reused) == len(records):
        raise ValueError("All Cases are recorded; this batch does not need resume")
    return {"source": source, "records": records, "rows": reused}
