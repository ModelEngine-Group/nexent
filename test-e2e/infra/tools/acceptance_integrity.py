"""Trace formal acceptance obligations without claiming semantic correctness."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree


def contract_issues(case: dict) -> list[str]:
    """Check references to every written step, expectation and forbidden effect."""
    obligations = case.get("acceptance")
    if obligations is None:
        return []
    if not isinstance(obligations, list) or not obligations:
        return ["acceptance must be a non-empty list"]
    allowed = {
        "steps": {step["order"] for step in case.get("steps", [])},
        "expected_results": set(range(1, len(case.get("expected_results", [])) + 1)),
        "forbidden_side_effects": set(range(1, len(case.get("forbidden_side_effects", [])) + 1)),
    }
    covered = {key: set() for key in allowed}
    ids, issues = set(), []
    for item in obligations:
        if not isinstance(item, dict) or set(item) - {"id", "description", *allowed}:
            issues.append("Invalid acceptance obligation fields")
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"AC-[A-Z0-9]+(?:-[A-Z0-9]+)*", identifier):
            issues.append("Acceptance ID must start with AC- and use uppercase identifiers")
        elif identifier in ids:
            issues.append(f"Duplicate acceptance ID: {identifier}")
        else:
            ids.add(identifier)
        if not isinstance(item.get("description"), str) or not item["description"].strip():
            issues.append(f"{identifier}: missing description")
        referenced = False
        for key, choices in allowed.items():
            values = item.get(key, [])
            if not isinstance(values, list) or any(type(value) is not int for value in values):
                issues.append(f"{identifier}: {key} must contain integer references")
                continue
            if len(values) != len(set(values)) or set(values) - choices:
                issues.append(f"{identifier}: invalid or duplicate {key} references")
            covered[key].update(values)
            referenced |= bool(values)
        if not referenced:
            issues.append(f"{identifier}: no contract references")
    for key, choices in allowed.items():
        missing = choices - covered[key]
        if missing:
            issues.append(f"Unmapped contract {key}: {sorted(missing)}")
    return issues


def binding_issues(case: dict, bindings: object, *, required: bool) -> list[str]:
    if "acceptance" not in case:
        return ["acceptance_bindings has no acceptance contract"] if bindings is not None else []
    if not isinstance(case["acceptance"], list):
        return ["Invalid acceptance contract"]
    if bindings is None and not required:
        return []
    if not isinstance(bindings, dict) or not bindings:
        return ["Every acceptance obligation requires actual test names in acceptance_bindings"]
    identifiers = {item["id"] for item in case["acceptance"]
                   if isinstance(item, dict) and isinstance(item.get("id"), str)}
    issues = []
    if set(bindings) != identifiers:
        issues.append("acceptance_bindings must match exactly the acceptance IDs")
    for identifier, names in bindings.items():
        if (not isinstance(names, list) or not names or
                any(not isinstance(name, str) or not name.strip() for name in names) or
                len(names) != len(set(names))):
            issues.append(f"{identifier}: provide unique, non-empty actual test names")
    return issues


def _outcomes(record: dict, directory: Path, execution_status: str) -> dict[str, list[str]]:
    framework = record["execution"]["implementations"][0]["framework"]
    outcomes = defaultdict(list)
    if framework in {"pytest", "vitest"}:
        try:
            tests = ElementTree.parse(directory / "junit.xml").getroot().iter("testcase")
            for test in tests:
                name = test.get("name", "")
                result = ("FAIL" if test.find("failure") is not None or test.find("error") is not None
                          else "BLOCKED" if test.find("skipped") is not None else "PASS")
                outcomes[name].append(result)
                classname = test.get("classname", "").split(".")[-1]
                if classname:
                    outcomes[f"{classname}::{name}"].append(result)
        except (OSError, ElementTree.ParseError):
            return {}
    elif framework == "custom":
        path = directory / "step-1.log"
        if path.is_file():
            for match in re.finditer(r"(?m)^\s*(not ok|ok) \d+ - (.+)$", path.read_text(encoding="utf-8")):
                name = match[2].strip()
                skipped = "# SKIP" in name or "# TODO" in name
                name = re.split(r"\s+# (?:SKIP|TODO)", name)[0]
                outcomes[name].append("BLOCKED" if skipped else "FAIL" if match[1] == "not ok" else "PASS")
    elif framework == "playwright":
        # run_one establishes the complete fixed journey audit before this call.
        outcomes[record["case_id"]].append(execution_status)
    return dict(outcomes)


def execution_report(record: dict, directory: Path, execution_status: str) -> dict:
    """Require actual execution of mapped tests; never certify assertion semantics."""
    obligations = record.get("acceptance", [])
    report = {"status": "UNREVIEWED", "semantic_review": "UNREVIEWED",
              "contract_hash": record.get("contract_hash"),
              "implementation_hash": record.get("execution", {}).get("implementation_hash"),
              "obligations": [], "required": len(obligations), "passed": 0}
    if not obligations:
        return report
    bindings = record.get("execution", {}).get("acceptance_bindings")
    report["bindings_sha256"] = hashlib.sha256(
        json.dumps(bindings, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    problems = binding_issues({"acceptance": obligations}, bindings, required=True)
    if problems:
        return dict(report, status="INCOMPLETE", issues=problems)
    outcomes = _outcomes(record, directory, execution_status)
    for item in obligations:
        observed = []
        missing = []
        for selector in bindings[item["id"]]:
            matches = [value for name, values in outcomes.items()
                       if name == selector or name.startswith(selector + "[") for value in values]
            if not matches:
                missing.append(selector)
            observed.extend(matches)
        state = ("FAIL" if "FAIL" in observed else "INCOMPLETE" if missing else
                 "BLOCKED" if any(value != "PASS" for value in observed) else "PASS")
        report["obligations"].append({"id": item["id"], "result": state, "missing_tests": missing})
        report["passed"] += state == "PASS"
    states = {item["result"] for item in report["obligations"]}
    report["status"] = ("FAIL" if "FAIL" in states else "INCOMPLETE" if "INCOMPLETE" in states else
                        "BLOCKED" if "BLOCKED" in states else
                        "MAPPED_EXECUTION_PASSED" if execution_status == "PASS" else "BLOCKED")
    return report
