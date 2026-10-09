#!/usr/bin/env python3
"""Deterministic queue and result writer for model-driven D4 journeys."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@contextmanager
def result_lock(results: Path):
    """Serialize result writers on Windows and POSIX using a stable sidecar."""
    with results.with_name(results.name + '.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


ALLOWED_RESULTS = {
    "PASS", "FAIL", "TIMEOUT", "AUTOMATION_ERROR", "BLOCKED",
    "BLOCKED_BY_DEPENDENCY", "SKIPPED", "SKIPPED_BY_SAFETY",
}
POLICY_RESULT = "SKIPPED_BY_POLICY"
PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEPENDENCY_ORDER = {
    case_id: index
    for index, case_id in enumerate(
        (
            "PW-AUTH-01", "PW-AUTH-02", "PW-AUTH-03", "PW-AUTH-04", "PW-PROFILE-01",
            "PW-RESOURCE-01", "PW-RESOURCE-02", "PW-RESOURCE-03", "PW-RESOURCE-04",
            "PW-RESOURCE-APIKEY-01", "PW-QUOTA-LOCAL-01",
            "PW-MODEL-01", "PW-MODEL-02", "PW-MEDIA-STT-01", "PW-MEDIA-VLM-01",
            "PW-KB-LOCAL-01", "PW-KB-AIDP-01", "PW-FILE-01",
            "PW-AGENT-01", "PW-AGENT-02", "PW-AGENT-03", "PW-NL2AGENT-01",
            "PW-PROMPT-01", "PW-PROMPT-02", "PW-AGENT-IMPORT-01", "PW-VERSION-01",
            "PW-MARKET-AGENT-01", "PW-SKILL-01", "PW-SKILL-02",
            "PW-MCP-REMOTE-01", "PW-MCP-CONTAINER-01", "PW-MCP-API-01",
            "PW-MCP-MARKET-01",
            "PW-A2A-DISCOVERY-01", "PW-A2A-PUBLISH-01",
            "PW-CHAT-01", "PW-CHAT-02", "PW-CHAT-03", "PW-CHAT-04", "PW-CHAT-05",
            "PW-SHARE-01", "PW-MEM-01", "PW-MEM-02", "PW-TASK-01",
            "PW-EVAL-SET-01", "PW-EVAL-RUN-01",
            "PW-UI-01", "PW-CHART-01", "PW-UI-02",
        )
    )
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc


def load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: result must be an object")
        records.append(value)
    return records


def result_index(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        case_id = str(record.get("case_id", "")).strip()
        if case_id:
            indexed.setdefault(case_id, []).append(record)
    return indexed


def checklist(text: Any, prefix: str) -> list[dict[str, str]]:
    """Convert V5 numbered prose to a stable, auditable ordered checklist."""
    values: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^\s*\d+[.、]\s*(.+)$", line)
        if match:
            values.append(match.group(1).strip())
        elif values:
            values[-1] += "\n" + line
        else:
            values.append(line)
    return [{"id": f"{prefix}-{index:02d}", "text": value} for index, value in enumerate(values, 1)]


def enrich_contract(item: dict[str, Any]) -> dict[str, Any]:
    required = ("preconditions", "local_assets", "steps", "assertions", "blocking_rule")
    missing = [name for name in required if not str(item.get(name) or "").strip()]
    if missing:
        raise ValueError(f"{item.get('id')}: V5 D4 contract has empty fields: {', '.join(missing)}")
    copied = dict(item)
    copied["precondition_items"] = checklist(item["preconditions"], "PRE")
    copied["step_items"] = checklist(item["steps"], "STEP")
    copied["assertion_items"] = checklist(item["assertions"], "ASSERT")
    if not copied["precondition_items"] or not copied["step_items"] or not copied["assertion_items"]:
        raise ValueError(f"{item.get('id')}: V5 D4 contract could not be converted to checklists")
    contract_source = {
        key: copied.get(key)
        for key in (
            "id", "source_sheet", "source_row", "title", "applicability", "business_goal",
            "page_route", "frontend_entry", "service_direction", "local_assets",
            "precondition_items", "step_items", "assertion_items", "external_dependency_policy",
            "selector_waiting_rules", "coverage", "cleanup", "blocking_rule",
            "playwright_boundary", "source_url",
        )
    }
    canonical = json.dumps(contract_source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    copied["contract_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return copied


def validate_assertions_file(result_root: Path, item: dict[str, Any], result: str, evidence: list[str]) -> None:
    matches = [value for value in evidence if value == f"d4/{item['id']}/assertions.json"]
    if len(matches) != 1:
        raise ValueError(f"{item['id']}: evidence must include exactly d4/{item['id']}/assertions.json")
    payload = load_json(result_root / matches[0])
    if payload.get("case_id") != item["id"]:
        raise ValueError(f"{item['id']}: assertions.json case_id mismatch")
    if payload.get("contract_hash") != item.get("contract_hash"):
        raise ValueError(f"{item['id']}: assertions.json contract_hash does not match V5 queue contract")
    expected_status = {
        "PASS": "PASS", "FAIL": "FAIL", "TIMEOUT": "FAIL", "AUTOMATION_ERROR": "FAIL",
        "BLOCKED": "BLOCKED", "BLOCKED_BY_DEPENDENCY": "BLOCKED",
        "SKIPPED": "SKIPPED", "SKIPPED_BY_SAFETY": "SKIPPED",
    }[result]
    if payload.get("status") != expected_status:
        raise ValueError(f"{item['id']}: assertions.json status must be {expected_status} for {result}")
    for payload_key, item_key in (
        ("preconditions", "precondition_items"), ("steps", "step_items"), ("assertions", "assertion_items")
    ):
        rows = payload.get(payload_key)
        if not isinstance(rows, list):
            raise ValueError(f"{item['id']}: assertions.json {payload_key} must be an array")
        actual_ids = [str(row.get("id")) for row in rows if isinstance(row, dict)]
        expected_ids = [row["id"] for row in item[item_key]]
        if actual_ids != expected_ids:
            raise ValueError(f"{item['id']}: assertions.json {payload_key} IDs/order differ from V5: expected {expected_ids}, got {actual_ids}")
        actual_names = [str(row.get("name")) for row in rows if isinstance(row, dict)]
        expected_names = [row["text"] for row in item[item_key]]
        if actual_names != expected_names:
            raise ValueError(f"{item['id']}: assertions.json {payload_key} names differ from V5 contract")
        if any(
            row.get("status") != "NOT_RUN" and not str(row.get("observed") or "").strip()
            for row in rows
        ):
            raise ValueError(f"{item['id']}: executed {payload_key} items require non-empty observed values")
        if result == "PASS" and any(row.get("status") != "PASS" for row in rows):
            raise ValueError(f"{item['id']}: PASS requires every {payload_key} item to be PASS")
    if result in {"FAIL", "TIMEOUT"}:
        if not any(Path(value).suffix.lower() in {".png", ".jpg", ".jpeg"} for value in evidence):
            raise ValueError(f"{item['id']}: {result} requires screenshot evidence")
    if result in {"FAIL", "TIMEOUT"}:
        if not any(Path(value).suffix.lower() == ".zip" and "trace" in Path(value).name.lower() for value in evidence):
            raise ValueError(f"{item['id']}: {result} requires Playwright trace zip evidence")
    if result == "AUTOMATION_ERROR" and len(evidence) < 2:
        raise ValueError(f"{item['id']}: AUTOMATION_ERROR requires structured failure evidence in addition to assertions.json")


def scaffold(args: argparse.Namespace) -> int:
    queue = load_json(args.queue)
    matches = [item for item in queue_items(queue) if str(item.get("id")) == args.case_id]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate D4 journey: {args.case_id}")
    item = matches[0]
    if item.get("policy_status") or item.get("applicability_status"):
        raise ValueError(f"{args.case_id}: preset result does not need assertions evidence")
    now = datetime.now(timezone.utc).isoformat()

    def pending(values: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            {"id": value["id"], "name": value["text"], "status": "NOT_RUN", "observed": ""}
            for value in values
        ]

    payload = {
        "schema_version": 1,
        "case_id": args.case_id,
        "contract_hash": item["contract_hash"],
        "started_at": now,
        "finished_at": now,
        "status": "BLOCKED",
        "preconditions": pending(item["precondition_items"]),
        "steps": pending(item["step_items"]),
        "assertions": pending(item["assertion_items"]),
        "cleanup": {"status": "NOT_REQUIRED", "details": ""},
        "console_errors": [],
        "unexpected_5xx": [],
        "notes": "",
    }
    output = args.result_dir / "d4" / args.case_id / "assertions.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError(f"{args.case_id}: assertions.json already exists")
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps({"scaffolded": args.case_id, "path": str(output)}, ensure_ascii=False))
    return 0


def d4_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("schema_version") != 1 or not isinstance(plan.get("items"), list):
        raise ValueError("execution plan must use schema_version 1 and contain items[]")
    selected = [
        item for item in plan["items"]
        if item.get("stage") == "D4" and item.get("kind") == "journey"
    ]
    if not selected:
        raise ValueError("execution plan contains no D4 journeys")
    ids = [str(item.get("id", "")).strip() for item in selected]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("D4 journey IDs must be non-empty and unique")
    selected.sort(key=lambda item: (DEPENDENCY_ORDER.get(str(item["id"]), len(DEPENDENCY_ORDER)), PRIORITY.get(str(item.get("priority")), 99), str(item["id"])))
    return selected


def queue_items(queue: dict[str, Any]) -> list[dict[str, Any]]:
    if queue.get("schema_version") != 1 or not isinstance(queue.get("items"), list):
        raise ValueError("D4 queue must use schema_version 1 and contain items[]")
    return queue["items"]


def ensure_relative_evidence(result_root: Path, values: list[str], require_files: bool) -> list[str]:
    normalized: list[str] = []
    for raw in values:
        value = raw.strip().replace("\\", "/")
        if not value:
            continue
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"evidence must be a RESULT_DIR-relative path: {raw}")
        resolved = (result_root / path).resolve()
        try:
            resolved.relative_to(result_root.resolve())
        except ValueError as exc:
            raise ValueError(f"evidence escapes RESULT_DIR: {raw}") from exc
        if require_files and not resolved.is_file():
            raise ValueError(f"evidence file does not exist: {value}")
        normalized.append(value)
    return list(dict.fromkeys(normalized))


def prepare(args: argparse.Namespace) -> int:
    plan = load_json(args.plan)
    items = d4_items(plan)
    records = load_results(args.results)
    indexed = result_index(records)
    queue: list[dict[str, Any]] = []
    active = 0
    excluded = 0
    applicability_skipped = 0
    # Run batch-scoped asset producers before consumers. Remaining cases keep
    # their V5 workbook order, so this is deterministic and auditable.
    producer_order = {
        case_id: index for index, case_id in enumerate((
            "PW-AGENT-01",
            "PW-MODEL-01",
            "PW-MODEL-02",
            "PW-KB-LOCAL-01",
            "PW-MCP-REMOTE-01",
            "PW-SKILL-01",
        ))
    }
    indexed_items = list(enumerate(items))
    indexed_items.sort(key=lambda pair: (
        0 if str(pair[1].get("id")) in producer_order else 1,
        producer_order.get(str(pair[1].get("id")), pair[0]),
    ))
    for _, item in indexed_items:
        case_id = str(item["id"])
        policy_status = item.get("policy_status")
        applicability_status = item.get("applicability_status")
        preset_status = policy_status or applicability_status
        existing = indexed.get(case_id, [])
        if preset_status:
            expected_status = str(preset_status)
            if expected_status not in {POLICY_RESULT, "SKIPPED"}:
                raise ValueError(f"{case_id}: unsupported preset status {expected_status}")
            excluded += expected_status == POLICY_RESULT
            applicability_skipped += expected_status == "SKIPPED"
            if len(existing) != 1 or existing[0].get("result") != expected_status:
                raise ValueError(f"{case_id}: preset result {expected_status} must be pre-populated exactly once")
        else:
            active += 1
            if existing:
                raise ValueError(f"{case_id}: active D4 result exists before execution")
            (args.result_dir / "d4" / case_id).mkdir(parents=True, exist_ok=True)
        copied = enrich_contract(item)
        copied["evidence_dir"] = f"d4/{case_id}"
        queue.append(copied)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_plan": str(args.plan),
        "baseline_branch": plan.get("baseline_branch"),
        "baseline_commit": plan.get("baseline_commit"),
        "tested_commit": plan.get("tested_commit"),
        "baseline_drift": bool(plan.get("baseline_drift")),
        "active_count": active,
        "policy_skipped_count": excluded,
        "applicability_skipped_count": applicability_skipped,
        "items": queue,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({"active": active, "policy_skipped": excluded, "applicability_skipped": applicability_skipped, "queue": str(args.output)}))
    return 0


def next_item(args: argparse.Namespace) -> int:
    queue = load_json(args.queue)
    indexed = result_index(load_results(args.results))
    for item in queue_items(queue):
        if item.get("policy_status") or item.get("applicability_status"):
            continue
        if not indexed.get(str(item["id"])):
            print(json.dumps(item, ensure_ascii=False, indent=2))
            return 0
    print(json.dumps({"complete": True}, ensure_ascii=False))
    return 0


def show(args: argparse.Namespace) -> int:
    queue = load_json(args.queue)
    matches = [item for item in queue_items(queue) if str(item.get("id")) == args.case_id]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate D4 journey: {args.case_id}")
    print(json.dumps(matches[0], ensure_ascii=False, indent=2))
    return 0


def record(args: argparse.Namespace) -> int:
    queue = load_json(args.queue)
    matches = [item for item in queue_items(queue) if str(item.get("id")) == args.case_id]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate D4 journey: {args.case_id}")
    item = matches[0]
    if item.get("policy_status") or item.get("applicability_status"):
        raise ValueError(f"{args.case_id}: pre-populated result is immutable")
    if args.result not in ALLOWED_RESULTS:
        raise ValueError(f"invalid result: {args.result}")
    if args.duration < 0:
        raise ValueError("duration must be non-negative")
    if args.result != "PASS" and not args.reason.strip():
        raise ValueError(f"{args.case_id}: {args.result} requires --reason")
    if args.result == "BLOCKED_BY_DEPENDENCY" and not args.dependency_case_id.strip():
        raise ValueError(f"{args.case_id}: BLOCKED_BY_DEPENDENCY requires --dependency-case-id")
    evidence = ensure_relative_evidence(args.result_dir, args.evidence, require_files=True)
    if not evidence:
        raise ValueError(f"{args.case_id}: every D4 result requires at least one evidence file")
    expected_prefix = f"d4/{args.case_id}/"
    outside = [path for path in evidence if not path.startswith(expected_prefix)]
    if outside:
        raise ValueError(f"{args.case_id}: evidence must stay under {expected_prefix}")
    validate_assertions_file(args.result_dir, item, args.result, evidence)
    record_value = {
        "case_id": args.case_id,
        "result": args.result,
        "stage": "D4",
        "duration_seconds": round(args.duration, 3),
        "failure_reason": args.reason.strip(),
        "analysis": args.analysis.strip() or "model-driven Playwright journey",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "evidence": evidence,
    }
    if args.dependency_case_id.strip():
        record_value["dependency_case_id"] = args.dependency_case_id.strip()
    args.results.parent.mkdir(parents=True, exist_ok=True)
    with result_lock(args.results), args.results.open("a+", encoding="utf-8") as handle:
        handle.seek(0)
        existing = [json.loads(line) for line in handle if line.strip()]
        if any(str(value.get("case_id")) == args.case_id for value in existing):
            raise ValueError(f"{args.case_id}: result already exists")
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(record_value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"recorded": args.case_id, "result": args.result}, ensure_ascii=False))
    return 0


def audit(args: argparse.Namespace) -> int:
    queue = load_json(args.queue)
    records = load_results(args.results)
    indexed = result_index(records)
    errors: list[str] = []
    active = 0
    excluded = 0
    applicability_skipped = 0
    for item in queue_items(queue):
        case_id = str(item["id"])
        matching = indexed.get(case_id, [])
        expected = item.get("policy_status") or item.get("applicability_status")
        active += expected is None
        excluded += expected == POLICY_RESULT
        applicability_skipped += expected == "SKIPPED"
        if len(matching) != 1:
            errors.append(f"{case_id}: expected one result, found {len(matching)}")
            continue
        actual = str(matching[0].get("result"))
        if expected and actual != expected:
            errors.append(f"{case_id}: expected {expected}, got {actual}")
        if not expected and actual not in ALLOWED_RESULTS:
            errors.append(f"{case_id}: invalid active result {actual}")
        if actual == "BLOCKED_BY_DEPENDENCY" and not matching[0].get("dependency_case_id"):
            errors.append(f"{case_id}: BLOCKED_BY_DEPENDENCY has no dependency_case_id")
        if not expected:
            try:
                evidence = ensure_relative_evidence(
                    args.result_dir,
                    [str(value) for value in matching[0].get("evidence", [])],
                    require_files=True,
                )
                if not evidence:
                    errors.append(f"{case_id}: result has no evidence")
                elif any(not value.startswith(f"d4/{case_id}/") for value in evidence):
                    errors.append(f"{case_id}: evidence is outside its journey directory")
                else:
                    validate_assertions_file(args.result_dir, item, actual, evidence)
            except ValueError as exc:
                errors.append(str(exc))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(json.dumps({"complete": True, "active": active, "policy_skipped": excluded, "applicability_skipped": applicability_skipped}))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--plan", type=Path, required=True)
    prepare_parser.add_argument("--results", type=Path, required=True)
    prepare_parser.add_argument("--result-dir", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    prepare_parser.set_defaults(function=prepare)

    for name, function in (("next", next_item), ("audit", audit)):
        command = commands.add_parser(name)
        command.add_argument("--queue", type=Path, required=True)
        command.add_argument("--results", type=Path, required=True)
        if name == "audit":
            command.add_argument("--result-dir", type=Path, required=True)
        command.set_defaults(function=function)

    show_parser = commands.add_parser("show")
    show_parser.add_argument("--queue", type=Path, required=True)
    show_parser.add_argument("--case-id", required=True)
    show_parser.set_defaults(function=show)

    scaffold_parser = commands.add_parser("scaffold")
    scaffold_parser.add_argument("--queue", type=Path, required=True)
    scaffold_parser.add_argument("--result-dir", type=Path, required=True)
    scaffold_parser.add_argument("--case-id", required=True)
    scaffold_parser.set_defaults(function=scaffold)

    record_parser = commands.add_parser("record")
    record_parser.add_argument("--queue", type=Path, required=True)
    record_parser.add_argument("--results", type=Path, required=True)
    record_parser.add_argument("--result-dir", type=Path, required=True)
    record_parser.add_argument("--case-id", required=True)
    record_parser.add_argument("--result", required=True)
    record_parser.add_argument("--duration", type=float, required=True)
    record_parser.add_argument("--reason", default="")
    record_parser.add_argument("--analysis", default="")
    record_parser.add_argument("--dependency-case-id", default="")
    record_parser.add_argument("--evidence", action="append", default=[])
    record_parser.set_defaults(function=record)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.function(args))
    except (ValueError, OSError) as exc:
        print(f"d4-control: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
