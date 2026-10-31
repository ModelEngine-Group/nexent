# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Default implementation validation must catch missing online preparation."""
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_execution
from validation_policy import apply_blocks, report

REPO = Path(__file__).resolve().parents[4]


def inspect_case(root, stage, preparation=None, phase="implementation"):
    cid = f"TEST-PREPARATION-{stage}-001"
    folder = root / "test-e2e/cases" / cid
    folder.mkdir(parents=True)
    (folder / "test.py").write_text("def test_proof(): pass\n", encoding="utf-8")
    raw = {"schema_version": "1.0", "case_id": cid,
           "implementations": [{"framework": "pytest", "file": "test.py", "selector": "test_proof"}]}
    if preparation is not None:
        raw["preparation"] = preparation
    (folder / "execution.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    schemas = root / "test-e2e/infra/schemas"
    schemas.mkdir(parents=True)
    shutil.copyfile(REPO / "test-e2e/infra/schemas/preparation.schema.json", schemas / "preparation.schema.json")
    case = {"feature_id": "TEST-PREPARATION", "status": "active", "automation": "automated"}
    with patch.object(validate_execution, "discover_documents", return_value=[]), \
            patch.object(validate_execution, "case_index", return_value=({cid: (stage, case, folder / "case.yaml")}, [])), \
            patch("deployment_exceptions.catalog", return_value={}):
        return validate_execution.inspect(root, phase)


@pytest.mark.parametrize("stage", ["D2", "D3", "D4", "D5"])
def test_default_gate_catches_omission_without_opt_in_and_daily_blocks_only_owner(tmp_path, stage):
    issues, registry = inspect_case(tmp_path, stage)
    assert len(issues) == 1 and issues[0].code == "CASE_PREPARATION_MISSING"
    original = registry["cases"] + [{"case_id": "OTHER-SMOKE-D1-001", "execution": {"test": True}}]
    result = report(tmp_path, issues, original)
    cid = registry["cases"][0]["case_id"]
    assert result["ready"] and result["blocked_cases"] == [cid]
    assert result["issues"][0]["case_id"] == cid
    selected = apply_blocks(original, result)
    assert len(selected) == 2 and selected[0]["asset_blocked"] and selected[0]["execution"] is None
    assert selected[1] == original[1] and original[0]["execution"]


@pytest.mark.parametrize("stage", ["D2", "D3", "D4", "D5"])
def test_explicit_self_contained_preparation_is_valid(tmp_path, stage):
    issues, registry = inspect_case(tmp_path, stage, {"families": []})
    assert not issues
    assert registry["cases"][0]["execution"]["preparation"] == {"families": []}


@pytest.mark.parametrize("stage,phase", [("D1", "implementation"), ("D5", "design")])
def test_offline_d1_and_preimplementation_design_do_not_require_declarations(tmp_path, stage, phase):
    issues, _ = inspect_case(tmp_path, stage, phase=phase)
    assert not issues


@pytest.mark.parametrize("preparation", [{}, {"families": ["unknown-factory"]}, {"families": "none"}])
def test_malformed_preparation_stays_fatal(tmp_path, preparation):
    issues, registry = inspect_case(tmp_path, "D5", preparation)
    assert issues and not report(tmp_path, issues, registry["cases"])["ready"]


def test_ops_declares_no_shared_factories_or_services():
    path = REPO / "test-e2e/cases/OPS-BOOTSTRAP-D5-001/execution.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["preparation"] == {"families": [], "anchors": False, "special_assets": False, "d4_groups": []}
    assert not raw.get("required_assets") and not raw.get("required_mock_services")
