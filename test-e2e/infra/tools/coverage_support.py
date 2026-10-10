"""Collect D1 coverage without mixing Python and frontend denominators."""

from __future__ import annotations

import json
from pathlib import Path


def python_arguments(repo: Path, directory: Path, env: dict[str, str]) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    env["COVERAGE_FILE"] = str(directory / ".coverage")
    arguments = [f"--cov={repo / 'backend'}", f"--cov={repo / 'sdk'}",
                 "--cov-branch", "--cov-context=test", "--cov-report="]
    config = repo / "test/.coveragerc"
    if config.is_file():
        arguments.append(f"--cov-config={config}")
    else:
        # Match Legacy UT's default coverage configuration discovery.
        arguments.append("--cov-config=.coveragerc")
    return arguments


def frontend_arguments(directory: Path) -> list[str]:
    return ["--coverage", f"--coverage.reportsDirectory={directory}"]


def python_inventory(repo: Path, data_files: list[Path]) -> list[str]:
    """Use a common in-scope inventory when tests import non-package sources."""
    from coverage import CoverageData

    files = set()
    for path in data_files:
        if not path.is_file():
            continue
        data = CoverageData(basename=str(path))
        data.read()
        for name in data.measured_files():
            source = Path(name).resolve()
            if source.is_file() and any(source.is_relative_to(repo / root) for root in ("backend", "sdk")):
                files.add(str(source))
    return sorted(files)


def python_report(repo: Path, directory: Path, data_files: list[Path], *, inventory: list[str] | None = None) -> dict:
    """Merge only the explicitly selected suite's data, keeping per-test contexts."""
    import coverage

    directory.mkdir(parents=True, exist_ok=True)
    config = repo / "test/.coveragerc"
    cov = coverage.Coverage(data_file=str(directory / ".coverage"),
                            config_file=str(config) if config.is_file() else True,
                            source=[str(repo / "backend"), str(repo / "sdk")], branch=True)
    available = [path for path in data_files if path.is_file()]
    if not available:
        raise ValueError("No Python coverage data was produced")
    from coverage import CoverageData

    merged = cov.get_data()
    empty = []
    for path in available:
        data = CoverageData(basename=str(path))
        data.read()
        if not data.has_arcs():
            if any(data.lines(name) for name in data.measured_files()):
                raise ValueError(f"Branch coverage is missing in {path}")
            # Source-inspection tests can pass without executing any product code.
            # Their empty, line-mode data cannot be merged into branch-mode data.
            empty.append(str(path))
            continue
        merged.update(data)
    if not merged.has_arcs():
        raise ValueError("No instrumented product code was executed")
    if inventory:
        merged.touch_files(inventory)
    cov.save()
    cov.json_report(outfile=str(directory / "coverage.json"))
    cov.xml_report(outfile=str(directory / "coverage.xml"))
    cov.html_report(directory=str(directory / "html"))
    report = json.loads((directory / "coverage.json").read_text(encoding="utf-8"))
    totals = report["totals"]
    summary = {
        "scope": ["backend", "sdk"], "data_files": len(available),
        "empty_data_files": empty, "missing_data_files": [str(path) for path in data_files if not path.is_file()],
        "lines": {"covered": totals["covered_lines"], "total": totals["num_statements"]},
        "branches": {"covered": totals["covered_branches"], "total": totals["num_branches"]},
    }
    for metric in ("lines", "branches"):
        counts = summary[metric]
        counts["percent"] = round(100 * counts["covered"] / counts["total"], 2) if counts["total"] else None
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
