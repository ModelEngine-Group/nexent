"""Snapshot Git test-asset provenance and explicit functional routing contacts."""
from __future__ import annotations

import json
import re
import subprocess

from jsonschema import Draft202012Validator, ValidationError
import yaml


def load_rules(repo):
    directory = repo / "test-e2e/infra/config"
    rules = yaml.safe_load((directory / "report-ownership.yaml").read_text(encoding="utf-8"))
    schema = json.loads((directory / "report-ownership.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(rules)
    for section in ("feature_overrides", "case_overrides"):
        if any(value not in rules["domains"] for value in rules[section].values()):
            raise ValueError("Ownership override references an unknown domain")
    for domain in rules["domains"].values():
        for pattern in domain["feature_id_patterns"]:
            re.compile(pattern)
    return rules


def route(record, feature, rules):
    """Use ownership metadata, never incidental keywords from a failure message."""
    case_id, feature_id = record["case_id"], record.get("feature_id", "")
    if case_id in rules["case_overrides"]:
        matches, basis = [rules["case_overrides"][case_id]], "Case override: " + case_id
    elif feature_id in rules["feature_overrides"]:
        matches, basis = [rules["feature_overrides"][feature_id]], "Feature override: " + feature_id
    else:
        category = feature.get("description", "").split(" / ", 1)[0]
        matches = [key for key, value in rules["domains"].items() if category in value["feature_categories"]]
        basis = "Feature category: " + category
        if not matches:
            matches = [key for key, value in rules["domains"].items()
                       if any(re.search(pattern, feature_id) for pattern in value["feature_id_patterns"])]
            basis = "explicit Feature-ID pattern: " + feature_id
    if len(matches) != 1:
        return {"status": "AMBIGUOUS" if matches else "UNASSIGNED", "owner": "Unassigned",
                "domain": "", "basis": basis, "candidates": matches}
    domain = rules["domains"][matches[0]]
    return {"status": "ASSIGNED", "owner": domain["owner"], "domain": domain["label"], "basis": basis}


def case_paths(record):
    directory = f"test-e2e/cases/{record['case_id']}"
    paths = {directory + "/case.yaml", directory + "/execution.yaml"}
    implementations = (record.get("execution") or {}).get("implementations") or []
    if implementations:
        paths.add(implementations[0]["file"])
    return paths


def git_provenance(repo, records, head):
    """Read one pinned history, not hundreds of unbounded per-Case git calls."""
    tracked = set().union(*(case_paths(record) for record in records)) if records else set()
    output = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "-C", str(repo), "log", head,
         "--format=%x1e%H%x00%an%x00%aI", "--name-only", "--", "test-e2e/cases"],
        timeout=60, encoding="utf-8", errors="replace", stderr=subprocess.PIPE)
    latest = {}
    for block in output.split("\x1e"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        commit, author, authored_at = lines[0].split("\x00", 2)
        for path in lines[1:]:
            if path in tracked:
                latest.setdefault(path, {"author": author, "commit": commit, "authored_at": authored_at,
                                         "file": path, "status": "COMMITTED"})
    dirty = set()
    for arguments in (("diff", "--name-only", "-z", "HEAD"), ("ls-files", "--others", "--exclude-standard", "-z")):
        names = subprocess.check_output(["git", "-C", str(repo), *arguments, "--", "test-e2e/cases"],
                                        timeout=30, encoding="utf-8", errors="replace", stderr=subprocess.PIPE)
        dirty.update(names.split("\x00"))
    # Insertion order follows git history, which is more reliable than author timestamps.
    order = {path: index for index, path in enumerate(latest)}
    result = {}
    for record in records:
        paths = case_paths(record)
        found = [path for path in paths if path in latest]
        value = dict(latest[min(found, key=order.get)]) if found else {"status": "UNKNOWN"}
        value["uncommitted_changes"] = bool(paths & dirty)
        result[record["case_id"]] = value
    return result


def enrich(repo, records, head):
    """Return immutable-plan metadata; unknown provenance must not invent an author."""
    warnings = []
    try:
        rules = load_rules(repo)
    except (OSError, ValueError, re.error, yaml.YAMLError, ValidationError):
        rules = None
        warnings.append("Responsibility routing configuration unavailable or invalid")
    try:
        authors = git_provenance(repo, records, head)
    except (OSError, ValueError, subprocess.SubprocessError):
        authors = {}
        warnings.append("Git test-asset history unavailable; authors are unknown")
    features = {}
    result = []
    for record in records:
        feature_id = record.get("feature_id", "")
        if feature_id not in features:
            path = repo / "test-e2e/features" / feature_id / "feature.yaml"
            try:
                features[feature_id] = yaml.safe_load(path.read_text(encoding="utf-8"))["feature"]
            except (OSError, KeyError, TypeError, yaml.YAMLError):
                features[feature_id] = {}
        responsibility = route(record, features[feature_id], rules) if rules else {
            "status": "UNASSIGNED", "owner": "Unassigned", "domain": "", "basis": "Invalid routing configuration"}
        result.append({**record, "git_last_modifier": authors.get(record["case_id"], {"status": "UNKNOWN"}),
                       "responsibility": responsibility})
    return result, warnings


def git_label(value):
    value = value or {}
    text = f"{value['author']} ({value['commit'][:12]})" if value.get("author") else "Unknown"
    return text + ("; uncommitted changes" if value.get("uncommitted_changes") else "")


def responsibility_label(value):
    value = value or {}
    if value.get("status") != "ASSIGNED":
        return "Unassigned" + (" (ambiguous)" if value.get("status") == "AMBIGUOUS" else "")
    return f"{value['domain']} / {value['owner']}"
