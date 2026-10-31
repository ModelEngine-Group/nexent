# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Offline naming checks preserve historical IDs and reject new ambiguous IDs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))

from case_naming import FROZEN_CATALOG_SHA256, LEGACY_CATALOG, LEGACY_SCHEMA, NEW_CASE_ID, naming_issues  # noqa: E402
from test_asset_lib import case_index, discover_documents  # noqa: E402
import validate_cases  # noqa: E402
import validate_test_assets  # noqa: E402


class CaseNamingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(REPO / "test-e2e/infra/schemas", self.root / "test-e2e/infra/schemas")
        self.write_catalog([])

    def write_catalog(self, case_ids):
        path = self.root / LEGACY_CATALOG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": "1.0", "baseline_commit": "a" * 40,
                                    "case_ids": case_ids}), encoding="utf-8")
        digest = hashlib.sha256(json.dumps(json.loads(path.read_text(encoding="utf-8")),
                                sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        pin = patch("case_naming.FROZEN_CATALOG_SHA256", digest)
        pin.start()
        self.addCleanup(pin.stop)

    def records(self, case_id, stage="D1", title="Reject invalid input without writing"):
        path = self.root / "test-e2e/cases" / case_id / "case.yaml"
        return {case_id: (stage, {"title": title}, path)}

    def write_case(self, case_id, stage="D1"):
        case = {
            "case_id": case_id, "feature_id": "FEATURE-01",
            "title": "Reject invalid input without writing", "type": "BE-UT",
            "priority": "P1", "status": "active", "automation": "automated",
            "objective": "Check component validation", "preconditions": [], "test_data": {},
            "steps": [{"order": 1, "action": "Validate input", "expected": "Reject input"}],
            "expected_results": ["Input is rejected"], "forbidden_side_effects": ["No write"],
            "unit_boundary": "Validation component", "inputs": [None], "assertions": ["No write"],
        }
        path = self.root / "test-e2e/cases" / case_id / "case.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"schema_version": "1.0", "stage": stage,
                                       "module": "CHECK-MODULE", "case": case}), encoding="utf-8")

    def test_new_ids_accept_all_five_stages_and_boundary_sequences(self):
        for stage in ("D1", "D2", "D3", "D4", "D5"):
            for sequence in ("001", "099", "999"):
                with self.subTest(stage=stage, sequence=sequence):
                    case_id = f"MODEL-PERMISSION-{stage}-{sequence}"
                    self.assertEqual(naming_issues(self.root, self.records(case_id, stage)), [])

    def test_multiword_capabilities_and_digit_tokens_are_allowed(self):
        for case_id in ("AGENT-REPO-SORT-MAIN-TAG-D4-001", "A2A-ERROR-D3-001"):
            stage = case_id.rsplit("-", 2)[1]
            self.assertEqual(naming_issues(self.root, self.records(case_id, stage)), [])

    def test_new_ids_reject_legacy_and_malformed_formats(self):
        for case_id in (
            "API-001", "PW-SKILL-02", "UT-FE-AUTO-02FA904A1C3AD386", "MODEL-D1-001",
            "MODEL-PERMISSION-D1-000", "MODEL-PERMISSION-D1-01", "MODEL-PERMISSION-D1-1000",
            "MODEL-PERMISSION-D0-001", "MODEL-PERMISSION-D6-001", "model-PERMISSION-D1-001",
            "MODEL_PERMISSION_D1_001", "MODEL--PERMISSION-D1-001", "模型-PERMISSION-D1-001",
            "MODEL-PERMISSION-D1-001\n", "MODEL-PERMISSION-D1-001 ",
        ):
            with self.subTest(case_id=case_id):
                issues = naming_issues(self.root, self.records(case_id))
                self.assertTrue(any(issue.location == "case_id" for issue in issues))

    def test_embedded_stage_must_match_the_contract(self):
        issues = naming_issues(self.root, self.records("MODEL-PERMISSION-D2-001", "D1"))
        self.assertTrue(any(issue.location == "stage" for issue in issues))

    def test_only_exact_frozen_historical_ids_are_exempt(self):
        self.write_catalog(["API-001", "UT-FE-AUTO-02FA904A1C3AD386"])
        for case_id in ("API-001", "UT-FE-AUTO-02FA904A1C3AD386"):
            self.assertEqual(naming_issues(self.root, self.records(case_id)), [])
        self.assertTrue(naming_issues(self.root, self.records("API-002")))
        self.assertTrue(naming_issues(self.root, self.records("UT-FE-AUTO-NEW")))

    def test_new_titles_reject_whitespace_without_requiring_one_language(self):
        case_id = "MODEL-PERMISSION-D1-001"
        for title in ("", "   ", "\t\n"):
            with self.subTest(title=title):
                self.assertTrue(any(issue.location == "title" for issue in
                                    naming_issues(self.root, self.records(case_id, title=title))))
        for title in ("模型不可用时禁止选择且不触发切换回调", "Reject unavailable models without callbacks"):
            self.assertEqual(naming_issues(self.root, self.records(case_id, title=title)), [])

    def test_frozen_catalog_cannot_hide_a_modern_stage_mismatch(self):
        self.write_catalog(["MODEL-PERMISSION-D2-001"])
        self.assertTrue(naming_issues(self.root, self.records("MODEL-PERMISSION-D2-001", "D1")))

    def test_invalid_duplicate_or_missing_catalog_fails_closed(self):
        path = self.root / LEGACY_CATALOG
        for contents in ("not json", "[]", '{}', json.dumps({"schema_version": "1.0",
                "baseline_commit": "a" * 40, "case_ids": ["API-001", "API-001"]})):
            with self.subTest(contents=contents):
                path.write_text(contents, encoding="utf-8")
                self.assertTrue(naming_issues(self.root, self.records("MODEL-PERMISSION-D1-001")))
        path.unlink()
        self.assertTrue(naming_issues(self.root, self.records("MODEL-PERMISSION-D1-001")))

    def test_missing_catalog_schema_fails_closed(self):
        (self.root / LEGACY_SCHEMA).unlink()
        self.assertTrue(naming_issues(self.root, self.records("MODEL-PERMISSION-D1-001")))

    def test_appending_an_exemption_or_replacing_the_anchor_is_rejected_without_git(self):
        self.write_catalog(["API-001"])
        path = self.root / LEGACY_CATALOG
        original = json.loads(path.read_text(encoding="utf-8"))
        for field, value in (("case_ids", ["API-001", "API-002"]), ("baseline_commit", "b" * 40)):
            with self.subTest(field=field):
                changed = {**original, field: value}
                path.write_text(json.dumps(changed), encoding="utf-8")
                issues = naming_issues(self.root, self.records("API-002"))
                self.assertTrue(any("reviewed baseline" in issue.message for issue in issues))
        self.assertFalse((self.root / ".git").exists())

    def test_case_validator_accepts_new_design_without_binding_or_git(self):
        self.write_case("MODEL-PERMISSION-D1-001")
        self.assertFalse((self.root / ".git").exists())
        self.assertEqual(validate_cases.validate(self.root), [])

    def test_empty_catalog_mode_keeps_its_existing_allow_empty_behavior(self):
        (self.root / LEGACY_CATALOG).unlink()
        self.assertEqual(validate_cases.validate(self.root, allow_empty=True), [])
        self.assertTrue(validate_cases.validate(self.root))

    def test_case_validator_keeps_modified_legacy_contract_compatible(self):
        self.write_catalog(["API-001"])
        self.write_case("API-001")
        self.assertEqual(validate_cases.validate(self.root), [])

    def test_both_unified_phases_reject_nonstandard_new_case(self):
        self.write_case("UNKNOWN-001")
        for phase in ("design", "implementation"):
            with self.subTest(phase=phase):
                issues = validate_test_assets.validate(self.root, phase, False)
                self.assertTrue(any("New Case ID must use" in issue.message for issue in issues))

    def test_folder_mismatch_remains_an_error_for_a_frozen_id(self):
        self.write_catalog(["API-002"])
        self.write_case("API-001")
        path = self.root / "test-e2e/cases/API-001/case.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document["case"]["case_id"] = "API-002"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        self.assertTrue(any("folder name" in issue.message for issue in validate_cases.validate(self.root)))

    def test_current_repository_stays_compatible_and_catalog_is_read_only(self):
        path = REPO / LEGACY_CATALOG
        before = path.read_bytes()
        cases, issues = case_index(discover_documents(REPO, "cases"))
        self.assertEqual(issues, [])
        with patch("case_naming.FROZEN_CATALOG_SHA256", FROZEN_CATALOG_SHA256):
            self.assertEqual(naming_issues(REPO, cases), [])
        self.assertEqual(path.read_bytes(), before)
        catalog = json.loads(before)
        self.assertEqual(catalog["case_ids"], sorted(catalog["case_ids"]))
        self.assertTrue(all(not NEW_CASE_ID.fullmatch(case_id) for case_id in catalog["case_ids"]))


if __name__ == "__main__":
    unittest.main()
