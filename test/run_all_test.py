import os
import subprocess
import sys
import logging
import multiprocessing

# Configure logger
logger = logging.getLogger("run_all_test")
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


def check_required_packages():
    """Check if required packages are available"""
    missing_packages = []

    # Check for pytest-cov
    try:
        import pytest_cov
    except ImportError:
        missing_packages.append("pytest-cov")

    # Check for coverage
    try:
        import coverage
    except ImportError:
        missing_packages.append("coverage")

    # Check for pytest-asyncio
    try:
        import pytest_asyncio
    except ImportError:
        missing_packages.append("pytest-asyncio")

    # Check for pytest-xdist
    try:
        import xdist
    except ImportError:
        missing_packages.append("pytest-xdist")

    if missing_packages:
        logger.error(
            f"Missing required packages: {', '.join(missing_packages)}")
        logger.error("Please install them using: pip install " +
                     " ".join(missing_packages))
        sys.exit(1)

    logger.info("All required packages are available")
    return True


def get_parallel_workers():
    """Get the optimal number of parallel workers based on CPU cores."""
    cpu_count = multiprocessing.cpu_count()
    # Use all available cores, but cap at 8 to avoid memory issues
    return min(cpu_count, 8)


def run_tests():
    """Run all tests using pytest with parallel execution and coverage."""
    # Get the script directory path
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Get project root directory (Nexent)
    project_root = os.path.abspath(os.path.join(current_dir, "../"))

    # Get the test directories path
    backend_test_dir = os.path.join(project_root, "test", "backend")
    sdk_test_dir = os.path.join(project_root, "test", "sdk")

    # Print the paths being searched to help with debugging
    logger.info(f"Searching for tests in: {backend_test_dir}")
    logger.info(f"Searching for tests in: {sdk_test_dir}")
    logger.info(f"Running tests from project root: {project_root}")

    # Change to project root directory
    os.chdir(project_root)

    # Check required packages
    check_required_packages()

    # Get parallel workers count
    workers = get_parallel_workers()
    logger.info(f"Using {workers} parallel workers for test execution")

    # Coverage data file path
    coverage_data_file = os.path.join(current_dir, '.coverage')
    config_file = os.path.join(current_dir, '.coveragerc')

    # Delete old coverage data if it exists
    if os.path.exists(coverage_data_file):
        try:
            os.remove(coverage_data_file)
            logger.info("Removed old coverage data.")
        except Exception as e:
            logger.warning(f"Could not remove old coverage data: {e}")

    # Define source directories for coverage
    backend_source = os.path.join(project_root, 'backend')
    sdk_source = os.path.join(project_root, 'sdk')

    # Build the pytest command with parallel execution
    # Use --tb=short for shorter tracebacks and -v for verbose output
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        backend_test_dir,   # All backend tests
        sdk_test_dir,       # All SDK tests
        "-n", str(workers),  # Parallel execution with N workers
        "-v",                # Verbose mode to show individual test results
        f"--cov={backend_source}",
        f"--cov={sdk_source}",
        "--cov-report=",
        "--cov-branch",      # Enable branch coverage
        "--cov-config=test/.coveragerc",
        "--tb=short",        # Shorter traceback format
        "-p", "no:warnings"  # Disable warning plugin to reduce noise
    ]

    # Set environment variables
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{project_root}:{env.get('PYTHONPATH', '')}"
    # For Windows systems, adjust path separator
    if sys.platform == 'win32':
        env["PYTHONPATH"] = f"{project_root};{env.get('PYTHONPATH', '')}"
    env["COVERAGE_FILE"] = coverage_data_file
    env["COVERAGE_PROCESS_START"] = config_file

    logger.info("Starting parallel test execution...")
    logger.info("=" * 60)

    # Run pytest with all tests at once
    # Note: We use stdout=None to inherit parent's stdout for real-time output in CI
    result = subprocess.run(
        cmd,
        stdout=None,  # Inherit stdout for real-time output
        stderr=subprocess.STDOUT,  # Merge stderr into stdout
        env=env
    )

    # Generate test summary report
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary (see above for detailed results)")
    logger.info("=" * 60)

    # Get test counts using pytest --collect-only
    # This is fast and doesn't run the tests
    collect_cmd = [
        sys.executable,
        "-m",
        "pytest",
        backend_test_dir,
        sdk_test_dir,
        "--collect-only",
        "-q"
    ]
    collect_result = subprocess.run(
        collect_cmd,
        capture_output=True,
        text=True,
        env=env
    )

    # Parse collected test count
    total_tests = 0
    passed_tests = 0
    failed_tests = 0

    for line in collect_result.stdout.split('\n'):
        if line.strip().startswith('collected '):
            try:
                total_tests = int(line.strip().split('collected ')[1].split()[0])
            except (IndexError, ValueError):
                pass

    # Calculate pass rate - if pytest exited with 0, all passed
    if result.returncode == 0:
        passed_tests = total_tests
        failed_tests = 0
    else:
        passed_tests = 0
        failed_tests = total_tests

    pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    logger.info(f"  Total Tests: {total_tests}")
    logger.info(f"  Passed: {passed_tests}")
    logger.info(f"  Failed: {failed_tests}")
    logger.info(f"  Pass Rate: {pass_rate:.1f}%")

    # Generate coverage reports
    logger.info("\n" + "=" * 60)
    logger.info("Code Coverage Report")
    logger.info("=" * 60)

    try:
        # Use coverage API to generate reports from the collected data
        import coverage
        cov = coverage.Coverage(
            data_file=coverage_data_file,
            config_file=config_file
        )
        cov.load()

        # Get measured files and check if they exist
        measured_files = cov.get_data().measured_files()
        missing_files = []
        for file_path in measured_files:
            if not os.path.exists(file_path):
                missing_files.append(file_path)
                logger.warning(f"Source file not found: {file_path}")

        if missing_files:
            logger.warning(
                f"\nFound {len(missing_files)} missing source files")
            logger.warning("Coverage report may be incomplete")

        # Console report
        try:
            total_coverage = cov.report(show_missing=True)
            logger.info(f"\nTotal Coverage: {total_coverage:.1f}%")

            # Generate HTML report
            html_dir = os.path.join(current_dir, 'coverage_html')
            cov.html_report(directory=html_dir)
            logger.info(f"\nHTML coverage report generated in: {html_dir}")

            # Generate XML report
            xml_file = os.path.join(current_dir, 'coverage.xml')
            cov.xml_report(outfile=xml_file)
            logger.info(f"XML coverage report generated: {xml_file}")
        except Exception as e:
            logger.error(
                f"Error generating coverage reports: {e}")
    except Exception as e:
        if "No data to report" in str(e) or "No data was collected" in str(e):
            logger.info("No coverage data collected. This might be because:")
            logger.info("1. No backend modules were imported during tests")
            logger.info("2. All tested modules are mocked")
            logger.info("3. Tests are not actually calling the backend code")
        else:
            logger.error(f"Error generating coverage report: {e}")

    # Return appropriate exit code based on test results
    if failed_tests > 0 or result.returncode != 0:
        logger.error(
            f"\nTest run failed: {failed_tests} tests failed out of {total_tests}")
        return False
    else:
        logger.info(f"\nTest run successful: {passed_tests} tests passed")
        return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
