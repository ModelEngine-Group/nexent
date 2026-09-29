"""Load Git-owned formal case assets and turn selected IDs into pytest parameters."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest
import yaml


_REPO = Path(__file__).resolve().parents[4]


@lru_cache(maxsize=5)
def load_stage_cases(stage: str) -> dict[str, dict]:
    catalog = {}
    for path in (_REPO / "test-e2e/cases").glob("*/case.yaml"):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload["stage"] != stage:
            continue
        item = payload["case"]
        case_id = str(item["case_id"])
        if case_id in catalog:
            raise RuntimeError(f"Duplicate {stage} case: {case_id}")
        catalog[case_id] = {**item, "id": case_id}
    return catalog


def case_params(stage: str, case_ids: list[str]):
    catalog = load_stage_cases(stage)
    missing = [case_id for case_id in case_ids if case_id not in catalog or catalog[case_id]["status"] != "active"]
    if missing:
        raise RuntimeError(f"{stage} case registry references unknown IDs: {missing}")
    return [
        pytest.param(
            catalog[case_id],
            marks=(pytest.mark.stage(stage), pytest.mark.case_id(case_id)),
            id=case_id,
        )
        for case_id in case_ids
    ]


def special_case_params(case_ids: list[str]):
    """Return D5 special-matrix rows with the same immutable ID markers."""
    catalog = load_stage_cases("D5")
    missing = [case_id for case_id in case_ids if case_id not in catalog or catalog[case_id]["status"] != "active"]
    if missing:
        raise RuntimeError(f"D5 special registry references unknown IDs: {missing}")
    return [
        pytest.param(
            catalog[case_id],
            marks=(pytest.mark.stage("D5"), pytest.mark.case_id(case_id), pytest.mark.special_id(case_id)),
            id=case_id,
        )
        for case_id in case_ids
    ]
