import os
import subprocess
import glob
import sys


def install_coverage():
    """Install coverage package if not available"""
    try:
        import coverage
        return True
    except ImportError:
        print("Coverage package not found. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "coverage"])
            return True
        except subprocess.CalledProcessError:
            print("Failed to install coverage package")
            return False


def run_tests():
    """Find and run all test files in the app directory using pytest"""
    # Get the script directory path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Get project root directory (Nexent)
    project_root = os.path.abspath(os.path.join(current_dir, "../.."))
    
    # Get the test directories path using relative path
    app_test_dir = os.path.join(current_dir, "app")
    services_test_dir = os.path.join(current_dir, "services")
    
    test_files = []
    
    # Check and collect test files from app directory
    if os.path.exists(app_test_dir):
        app_test_files = glob.glob(os.path.join(app_test_dir, "test_*.py"))
        test_files.extend(app_test_files)
    else:
        print(f"Directory not found: {app_test_dir}")
    
    # Check and collect test files from services directory
    if os.path.exists(services_test_dir):
        services_test_files = glob.glob(os.path.join(services_test_dir, "test_*.py"))
        test_files.extend(services_test_files)
    else:
        print(f"Directory not found: {services_test_dir}")
    
    if not test_files:
        print(f"No test files found in {app_test_dir} or {services_test_dir}")
        return False
    
    print(f"Found {len(test_files)} test files to run")
    print(f"Running tests from project root: {project_root}")
    
    # Change to project root directory
    os.chdir(project_root)
    
    # Check if coverage should be used
    use_coverage = install_coverage()
    
    if use_coverage:
        try:
            import coverage
            # Initialize coverage with configuration
            cov = coverage.Coverage(
                source=[
                    str(os.path.join(project_root, 'backend'))  # Backend directory
                ],
                omit=[
                    '*/test*',
                    '*/tests/*',
                    '*/__pycache__/*',
                    '*/venv/*',
                    '*/env/*',
                    '*/.venv/*',
                    '*/__init__.py'  # Exclude empty __init__.py files from coverage
                ],
                config_file=False  # Don't use config file, use programmatic config
            )
            # Start coverage measurement
            cov.start()
        except Exception as e:
            print(f"Error initializing coverage: {e}")
            use_coverage = False
    
    # Results tracking
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    test_results = []
    
    # Run each test file
    for test_file in test_files:
        # Get test file path relative to project root
        rel_path = os.path.relpath(test_file, project_root)
        # Replace backslashes with forward slashes for pytest
        rel_path = rel_path.replace("\\", "/")
        
        print(f"\nRunning tests in {rel_path}")
        print("-" * 50)
        
        # Run the test using pytest from project root
        result = subprocess.run(["python", "-m", "pytest", rel_path, "-v"], 
                               capture_output=True, text=True)
        
        # Print the output
        print(result.stdout)
        if result.stderr:
            print("Errors:")
            print(result.stderr)
        
        # Count tests and results
        test_info = {
            'file': rel_path,
            'success': result.returncode == 0,
            'output': result.stdout
        }
        test_results.append(test_info)
        
        # Parse pytest output to get test counts
        file_total = file_passed = 0
        for line in result.stdout.split('\n'):
            if line.strip().startswith('collected '):
                try:
                    file_total = int(line.strip().split()[1])
                except (IndexError, ValueError):
                    pass
            if ' passed' in line and ' failed' in line and ' error' in line:
                try:
                    parts = line.strip().split()
                    for part in parts:
                        if part.endswith(' passed'):
                            file_passed = int(part.split(' ')[0])
                except (IndexError, ValueError):
                    pass
        
        total_tests += file_total
        passed_tests += file_passed
        failed_tests += file_total - file_passed
    
    # Generate test summary report
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    # Print per-file results
    for test_result in test_results:
        status = "✅ PASSED" if test_result['success'] else "❌ FAILED"
        print(f"{status} - {test_result['file']}")
    
    # Calculate pass rate
    pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    print("\nTest Results:")
    print(f"  Total Tests: {total_tests}")
    print(f"  Passed: {passed_tests}")
    print(f"  Failed: {failed_tests}")
    print(f"  Pass Rate: {pass_rate:.1f}%")
    
    # Generate coverage report if applicable
    if use_coverage:
        try:
            # Stop coverage measurement
            cov.stop()
            cov.save()
            
            # Print coverage report
            print("\n" + "=" * 60)
            print("Code Coverage Report")
            print("=" * 60)
            
            try:
                # Console report
                total_coverage = cov.report(show_missing=True)
                print(f"\nTotal Coverage: {total_coverage:.1f}%")
                
                # Generate HTML report
                html_dir = os.path.join(current_dir, 'coverage_html')
                cov.html_report(directory=html_dir)
                print(f"\nHTML coverage report generated in: {html_dir}")
                
                # Generate XML report
                xml_file = os.path.join(current_dir, 'coverage.xml')
                cov.xml_report(outfile=xml_file)
                print(f"XML coverage report generated: {xml_file}")
            except coverage.exceptions.NoDataError:
                print("No coverage data collected. This might be because:")
                print("1. No backend modules were imported during tests")
                print("2. All tested modules are mocked")
                print("3. Tests are not actually calling the backend code")
        except Exception as e:
            print(f"Error generating coverage report: {e}")
    
    print("\nAll tests completed")
    return True


if __name__ == "__main__":
    run_tests()
