"""Generate portable, read-only Feature -> Case navigation pages."""

from __future__ import annotations

import argparse
from pathlib import Path

from test_asset_lib import case_index, discover_documents, feature_index, repository_root


def expected_pages(root: Path) -> dict[Path, str]:
    features, _, feature_issues = feature_index(discover_documents(root, "features"))
    cases, case_issues = case_index(discover_documents(root, "cases"))
    if feature_issues or case_issues:
        raise ValueError("Feature and Case documents must pass validation first")
    owned: dict[str, list[tuple[str, str, str]]] = {key: [] for key in features}
    for case_id, (stage, case, _) in cases.items():
        owner = case["feature_id"]
        if owner not in owned:
            raise ValueError(f"{case_id}: unknown Feature {owner}")
        owned[owner].append((stage, case_id, case["status"]))
    pages = {}
    for feature_id in sorted(features):
        target = root / "test-e2e/features" / feature_id / "cases.md"
        lines = [f"# {feature_id} 关联用例", "", "此页由结构化用例生成，不手工编辑。", ""]
        for stage, case_id, status in sorted(owned[feature_id]):
            lines.append(f"- {stage} [{case_id}](../../cases/{case_id}/case.yaml) · {status}")
        pages[target] = "\n".join(lines) + "\n"
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = repository_root(args.root)
    stale = []
    for target, content in expected_pages(root).items():
        if not target.is_file() or target.read_text(encoding="utf-8") != content:
            if args.check:
                stale.append(target.relative_to(root).as_posix())
            else:
                target.write_text(content, encoding="utf-8")
    if stale:
        print("Stale Feature navigation pages: " + ", ".join(stale))
        return 1
    print("Feature navigation pages are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
