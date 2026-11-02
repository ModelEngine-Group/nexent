# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit identity migrations preserve valid bindings and live references."""
import ast
import json
from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from case_naming import NEW_CASE_ID
from test_asset_lib import case_index, discover_documents
from validate_execution import inspect

REPO = Path(__file__).resolve().parents[4]
MAPPING = REPO / "test-e2e/infra/migration/case-id-renames-20261102.json"


def renames():
    return json.loads(MAPPING.read_text(encoding="utf-8"))["renames"]


def test_mapping_is_bijective_and_matches_the_original_proving_stage():
    rows = renames()
    assert len(rows) == 7
    old = {row["old_case_id"] for row in rows}
    new = {row["new_case_id"] for row in rows}
    assert len(old) == len(new) == len(rows) and not old & new
    for row in rows:
        match = NEW_CASE_ID.fullmatch(row["new_case_id"])
        assert match and match["stage"] == row["stage"]


def test_new_ids_resolve_once_and_no_old_identity_remains_in_live_yaml():
    cases, issues = case_index(discover_documents(REPO, "cases"))
    assert not issues
    old = {row["old_case_id"] for row in renames()}
    pattern = re.compile(r"(?<![A-Z0-9-])(?:" + "|".join(re.escape(cid) for cid in old) + r")(?![A-Z0-9-])")
    for row in renames():
        assert row["old_case_id"] not in cases
        stage, _, path = cases[row["new_case_id"]]
        assert stage == row["stage"] and path.parent.name == row["new_case_id"]
        assert not (path.parent.parent / row["old_case_id"]).exists()
    for kind in ("cases", "features", "changes"):
        for document in discover_documents(REPO, kind):
            assert not pattern.search(document.path.read_text(encoding="utf-8")), document.path


def test_executable_case_markers_and_id_derived_selectors_use_new_identity():
    _, registry = inspect(REPO)
    records = {row["case_id"]: row for row in registry["cases"]}
    for row in renames():
        record = records[row["new_case_id"]]
        if not record["execution"]:
            continue
        primary = record["execution"]["implementations"][0]
        text = (REPO / primary["file"]).read_text(encoding="utf-8")
        tree = ast.parse(text)
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
        markers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "case_id":
                argument = node.args[0]
                markers.append(argument.value if isinstance(argument, ast.Constant) else constants.get(argument.id))
        assert markers and set(markers) == {row["new_case_id"]}
        assert row["old_case_id"] not in {value for value in constants.values() if isinstance(value, str)}
        assert primary["selector"] in text
        binding = yaml.safe_load((REPO / "test-e2e/cases" / row["new_case_id"] / "execution.yaml").read_text(encoding="utf-8"))
        assert binding["case_id"] == row["new_case_id"]
