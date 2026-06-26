import importlib.util
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


logger = logging.getLogger("run_all_test")
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(console_handler)


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def check_required_packages() -> None:
    required = {
        "pytest_cov": "pytest-cov",
        "coverage": "coverage",
        "pytest_asyncio": "pytest-asyncio",
    }
    missing_packages = [package for module, package in required.items() if not _has_module(module)]
    if missing_packages:
        logger.error("Missing required packages: %s", ", ".join(missing_packages))
        logger.error("Please install them using: pip install %s", " ".join(missing_packages))
        sys.exit(1)
    logger.info("All required packages are available")


def _worker_count(total_files: int) -> int:
    raw_workers = os.environ.get("NEXENT_PYTEST_WORKERS", "auto").strip().lower()
    if raw_workers in {"", "0", "false", "none", "off"}:
        return 1
    if raw_workers == "auto":
        return max(1, min(os.cpu_count() or 1, total_files))
    try:
        return max(1, min(int(raw_workers), total_files))
    except ValueError:
        logger.warning("Invalid NEXENT_PYTEST_WORKERS=%s; falling back to serial", raw_workers)
        return 1


def _file_timeout_seconds() -> int:
    raw_timeout = os.environ.get("NEXENT_PYTEST_FILE_TIMEOUT", "600").strip()
    if raw_timeout in {"", "0", "false", "none", "off"}:
        return 0
    try:
        return max(1, int(raw_timeout))
    except ValueError:
        logger.warning("Invalid NEXENT_PYTEST_FILE_TIMEOUT=%s; falling back to 600 seconds", raw_timeout)
        return 600


def _target_paths(project_root: Path) -> list[Path]:
    raw_targets = os.environ.get("NEXENT_PYTEST_TARGETS")
    if raw_targets:
        return [(project_root / target).resolve() for target in raw_targets.split()]
    return [
        project_root / "test" / "backend",
        project_root / "test" / "sdk",
    ]


def _collect_test_files(project_root: Path) -> list[Path]:
    test_files: list[Path] = []
    for target in _target_paths(project_root):
        if target.is_file():
            test_files.append(target)
            continue
        if target.is_dir():
            test_files.extend(sorted(target.rglob("test_*.py")))
        else:
            logger.warning("Test target not found: %s", target)
    return sorted({path.resolve() for path in test_files})


def _run_test_file(
    *,
    index: int,
    test_file: Path,
    project_root: Path,
    backend_source: Path,
    sdk_source: Path,
    coverage_dir: Path,
    timeout_seconds: int,
) -> dict:
    rel_path = test_file.relative_to(project_root).as_posix()
    coverage_file = coverage_dir / f".coverage.{index}"
    cov_config = project_root / "test" / ".coveragerc"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        rel_path,
        "-q",
        f"--cov={backend_source}",
        f"--cov={sdk_source}",
        "--cov-report=",
        "--cov-branch",
        "--disable-warnings",
    ]
    if cov_config.exists():
        cmd.append("--cov-config=test/.coveragerc")

    env = os.environ.copy()
    path_separator = ";" if sys.platform == "win32" else ":"
    env["PYTHONPATH"] = f"{project_root}{path_separator}{env.get('PYTHONPATH', '')}"
    env["COVERAGE_FILE"] = str(coverage_file)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds or None,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return {
            "file": rel_path,
            "returncode": 124,
            "stdout": stdout,
            "stderr": stderr + f"\nTimed out after {timeout_seconds} seconds\n",
        }
    return {
        "file": rel_path,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _print_file_result(result: dict) -> None:
    summary = "execution failed"
    for line in reversed(result["stdout"].splitlines()):
        if " passed" in line and " in " in line:
            summary = line.strip()
            break
        if (" failed" in line or " error" in line or " errors" in line) and " in " in line:
            summary = line.strip()
            break
    status = "PASS" if result["returncode"] == 0 else "FAIL"
    logger.info("%-60s %s | %s", result["file"], status, summary)


def _combine_coverage(current_dir: Path, project_root: Path) -> bool:
    coverage_data_file = current_dir / ".coverage"
    coverage_xml_file = current_dir / "coverage.xml"
    cov_config = current_dir / ".coveragerc"
    for path in (coverage_data_file, coverage_xml_file):
        if path.exists():
            path.unlink()

    combine_cmd = [
        sys.executable,
        "-m",
        "coverage",
        "combine",
        "--data-file",
        str(coverage_data_file),
        str(current_dir),
    ]
    xml_cmd = [
        sys.executable,
        "-m",
        "coverage",
        "xml",
        "-o",
        str(coverage_xml_file),
        "--data-file",
        str(coverage_data_file),
    ]
    if cov_config.exists():
        xml_cmd[4:4] = ["--rcfile=test/.coveragerc"]
    combine = subprocess.run(combine_cmd, cwd=project_root, text=True, capture_output=True)
    if combine.returncode != 0:
        logger.error("Coverage combine failed:\n%s\n%s", combine.stdout, combine.stderr)
        return False
    xml = subprocess.run(xml_cmd, cwd=project_root, text=True, capture_output=True)
    if xml.returncode != 0:
        logger.error("Coverage XML generation failed:\n%s\n%s", xml.stdout, xml.stderr)
        return False
    logger.info("Coverage XML file generated: %s", coverage_xml_file)
    return True


def run_tests() -> bool:
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    backend_source = project_root / "backend"
    sdk_source = project_root / "sdk"

    os.chdir(project_root)
    check_required_packages()

    test_files = _collect_test_files(project_root)
    if not test_files:
        logger.error("No test files found")
        return False

    for coverage_artifact in [current_dir / ".coverage", *current_dir.glob(".coverage.*")]:
        if coverage_artifact.exists():
            coverage_artifact.unlink()
    coverage_xml = current_dir / "coverage.xml"
    if coverage_xml.exists():
        coverage_xml.unlink()

    workers = _worker_count(len(test_files))
    timeout_seconds = _file_timeout_seconds()
    logger.info("Found %s test files", len(test_files))
    logger.info("Running with %s file worker(s)", workers)
    if timeout_seconds:
        logger.info("Per-file timeout: %s seconds", timeout_seconds)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _run_test_file,
                index=index,
                test_file=test_file,
                project_root=project_root,
                backend_source=backend_source,
                sdk_source=sdk_source,
                coverage_dir=current_dir,
                timeout_seconds=timeout_seconds,
            )
            for index, test_file in enumerate(test_files)
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            _print_file_result(result)

    failed = [result for result in results if result["returncode"] != 0]
    if failed:
        logger.error("\nFailed test files: %s", len(failed))
        for result in failed[:10]:
            logger.error("\n%s\n%s\n%s", result["file"], result["stdout"][-4000:], result["stderr"][-2000:])

    coverage_ok = _combine_coverage(current_dir, project_root)
    return not failed and coverage_ok


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
