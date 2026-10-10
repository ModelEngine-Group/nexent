"""Generated registry and Excel are optional local views, not checkout prerequisites."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import validate_test_assets  # noqa: E402


class GeneratedViewTests(unittest.TestCase):
    def validate(self, root: Path):
        def write_workbook(_root: Path, output: Path) -> None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("fresh", encoding="utf-8")

        with patch.object(validate_test_assets.validate_features, "validate", return_value=[]), \
                patch.object(validate_test_assets.validate_cases, "validate", return_value=[]), \
                patch.object(validate_test_assets.validate_changes, "validate", return_value=[]), \
                patch.object(validate_test_assets.validate_traceability, "validate", return_value=[]), \
                patch.object(validate_test_assets.validate_execution, "inspect", return_value=([], {"cases": []})), \
                patch.object(validate_test_assets.generate_feature_links, "expected_pages", return_value={}), \
                patch.object(validate_test_assets.generate_excel, "write_workbook", side_effect=write_workbook), \
                patch.object(validate_test_assets.generate_excel, "workbook_snapshot",
                             side_effect=lambda path: path.read_text(encoding="utf-8")):
            return validate_test_assets.validate(root, "implementation", False)

    def test_missing_local_views_do_not_block_clean_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.validate(Path(temporary)), [])

    def test_existing_stale_local_views_still_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "test-e2e/infra/generated"
            generated.mkdir(parents=True)
            (generated / "registry.json").write_text("stale", encoding="utf-8")
            (generated / "Nexent_测试基线.xlsx").write_text("stale", encoding="utf-8")
            messages = [issue.message for issue in self.validate(root)]
            self.assertEqual(messages, ["Generated execution registry is stale", "Generated Excel view is stale"])


if __name__ == "__main__":
    unittest.main()
