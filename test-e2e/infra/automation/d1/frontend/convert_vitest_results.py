"""Append Vitest JSON results to the shared per-case JSONL checkpoint."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


# Search the complete ancestor/title string.  Generated component cases use an
# AUTO hash while legacy cases use three digits; neither must be the first
# token in a Vitest title.
CASE_RE = re.compile(r"\b(UT-FE-(?:\d{3}|AUTO-[0-9A-F]{16}))\b", re.IGNORECASE)


def _redact_reason(value: str) -> str:
    value = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer ***", value)
    return re.sub(
        r"(?i)(api[_-]?key|access[_-]?key|password|secret|token)(\s*[:=]\s*)['\"]?[^\s,'\"}]+",
        r"\1\2***",
        value,
    )


def _load_checkpoint(path: Path) -> tuple[list[dict], dict[str, int]]:
    records: list[dict] = []
    positions: dict[str, int] = {}
    if not path.is_file():
        return records, positions
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        record = json.loads(raw)
        case_id = str(record.get("case_id") or "").strip()
        if not case_id:
            raise ValueError(f"checkpoint line {line_number} has no case_id")
        if case_id in positions:
            raise ValueError(f"checkpoint contains duplicate case_id: {case_id}")
        positions[case_id] = len(records)
        records.append(record)
    return records, positions


def _write_checkpoint_atomic(path: Path, records: list[dict]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--result-dir", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result_dir = Path(args.result_dir).resolve()
    target = result_dir / "checkpoints" / "results.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    checkpoint, positions = _load_checkpoint(target)
    seen: set[str] = set()
    converted: list[dict] = []
    ignored_without_case_id = 0
    for suite in payload.get("testResults", []):
        for assertion in suite.get("assertionResults", []):
            title = " ".join([*assertion.get("ancestorTitles", []), assertion.get("title", "")])
            match = CASE_RE.search(title)
            if not match:
                # The frontend suite also contains product/helper tests that are
                # intentionally outside the V5 contract.  Only explicitly bound
                # UT-FE assertions belong in the shared per-case checkpoint;
                # finalize_daily.py remains responsible for proving that every
                # expected V5 UT-FE id was recorded.
                ignored_without_case_id += 1
                continue
            case_id = match.group(1).upper()
            if case_id in seen:
                raise ValueError(f"duplicate Vitest case id: {case_id}")
            seen.add(case_id)
            status = assertion.get("status")
            result = {"passed": "PASS", "failed": "FAIL", "pending": "BLOCKED"}.get(status, "BLOCKED")
            reason = _redact_reason("\n".join(assertion.get("failureMessages") or []))[:4000]
            evidence: list[str] = []
            if result in {"FAIL", "BLOCKED"}:
                evidence_path = result_dir / "d1" / case_id / "failure.json"
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                evidence_path.write_text(
                    json.dumps(
                        {
                            "case_id": case_id,
                            "result": result,
                            "reason": reason,
                            "source": "vitest",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                evidence.append(evidence_path.relative_to(result_dir).as_posix())
            converted.append({
                "case_id": case_id,
                "result": result,
                "stage": "D1",
                "duration_seconds": round(float(assertion.get("duration") or 0) / 1000, 3),
                "failure_reason": reason,
                "analysis": "repository case-local frontend component automation",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "evidence": evidence,
            })
    for record in converted:
        case_id = record["case_id"]
        if case_id not in positions:
            positions[case_id] = len(checkpoint)
            checkpoint.append(record)
            continue
        current = checkpoint[positions[case_id]]
        if current.get("stage") != "D1" or current.get("result") != record["result"]:
            raise ValueError(
                f"existing checkpoint result conflicts for {case_id}: "
                f"{current.get('stage')}/{current.get('result')} vs D1/{record['result']}"
            )
        # Idempotent repair mode: preserve the original execution metadata and
        # only attach newly materialized evidence to an existing Vitest result.
        current["evidence"] = record["evidence"]
        if not current.get("failure_reason"):
            current["failure_reason"] = record["failure_reason"]
    _write_checkpoint_atomic(target, checkpoint)
    print(
        json.dumps(
            {
                "converted": len(converted),
                "ignored_without_case_id": ignored_without_case_id,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
