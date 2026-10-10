"""Read-only prerequisite migration planner; never approves or rewrites Cases.

Run after audit_external_suite.py. Source scripts must be the trusted original
suite: their pure review functions are imported, but freeze/main is never run.
Output is review evidence, NOT an execution input or an alternative manifest.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from validate_execution import inspect
from suite_runtime import save


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_evidence(source, repo, report):
    """Reject stale receipts before proposing any prerequisites."""
    if digest(source / "auto_test/implementation-manifest.json") != report["source_manifest_sha256"]:
        raise ValueError("Source manifest changed; repeat direct comparison")
    for row in report["scripts"]:
        if digest(repo / row["target"]) != row["target_sha256"]:
            raise ValueError(f"Target changed after direct comparison: {row['case_id']}")
        for relative, expected in row["source_sha256"].items():
            if digest(source / relative) != expected:
                raise ValueError(f"Source changed after direct comparison: {row['case_id']}")


def build(source, repo, report):
    check_evidence(source, repo, report)
    issues, registry = inspect(repo)
    if issues:
        raise ValueError("Formal execution validation failed; resolve before prerequisite migration")
    # CLI runs in a fresh interpreter. Never call the source review freeze API.
    sys.path.insert(0, str(source / "scripts"))
    from local_asset_plan import prerequisite_plan
    from reviewed_self_preparing import online_preparation_cases
    from d4_asset_plan import select_groups, verified_journey

    auto = source / "auto_test"
    bindings = {row["case_id"]: row for row in json.loads((auto / "implementation-manifest.json").read_text())['cases']}
    original = prerequisite_plan(auto, list(bindings), bindings)
    reviewed = set(original["reviewed_without_kb_agent_producers"])
    online = set(online_preparation_cases(auto, list(bindings), bindings))
    scripts = {row["case_id"]: row for row in report["scripts"]}
    rows = []
    for record in registry["cases"]:
        cid = record["case_id"]
        if record["stage"] == "D1":
            continue
        row = {"case_id": cid, "stage": record["stage"], "case_status": record["status"]}
        if not record["execution"] or record["status"] != "active":
            row["disposition"] = "inactive_or_unbound"
        elif cid not in bindings:
            row["disposition"] = "repository_only_needs_review"
        elif cid not in reviewed:
            row["disposition"] = "source_review_missing_or_stale"
        elif scripts.get(cid, {}).get("outcome", "different_needs_review") in {"different_needs_review", "no_source_binding", "source_file_missing"}:
            row["disposition"] = "implementation_difference_needs_review"
        else:
            row["disposition"] = "candidate_requires_dependency_review"
            row["candidate"] = {
                "families": original["case_factory_families"].get(cid, []),
                "anchors": cid in online,
                "special_assets": cid in {"PERF-03", "PERF-04", "PERF-06", "PERF-10", "REL-02"},
                "d4_groups": [],
            }
            if record["stage"] == "D4":
                if not verified_journey(auto, cid, bindings[cid]):
                    raise ValueError(f"D4 dependency review changed: {cid}")
                row["candidate"]["d4_groups"] = select_groups(auto, [cid], auto / "d4/asset-dependencies.json")
            row["script_comparison"] = scripts[cid]["outcome"]
        rows.append(row)
    # Pin ALL target preparation/support code, not just a one-line Case wrapper.
    support = {p.relative_to(repo).as_posix(): digest(p)
               for p in sorted((repo / "test-e2e/infra/automation").rglob("*"))
               if p.is_file() and p.suffix in {".py", ".ts", ".json", ".mjs"}
               and not set(p.parts) & {"node_modules", "__pycache__", "test-results"}}
    rules = {f"scripts/{name}": digest(source / "scripts" / name) for name in
             ("local_asset_plan.py", "reviewed_self_preparing.py", "d4_asset_plan.py")}
    return {"schema_version": 1, "execution_authorized": False,
            "purpose": "Migration review evidence only; not consumed by the runner",
            "source_rule_sha256": rules, "target_support_sha256": support,
            "counts": dict(Counter(row["disposition"] for row in rows)), "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    source = args.source_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(source) or output.is_relative_to(repo / "test-e2e/cases"):
        parser.error("Audit output must not overwrite source suite or formal Cases")
    result = build(source, repo, json.loads(args.comparison.read_text(encoding="utf-8")))
    save(output, result)
    print(json.dumps(result["counts"], indent=2))


if __name__ == "__main__":
    main()
