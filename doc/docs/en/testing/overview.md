# Testing Overview

Nexent provides a comprehensive testing framework that ensures code quality and reliability across all components. This guide covers the testing strategy, tools, and best practices used throughout the project.

## Testing Philosophy

Our testing approach is built on four core principles:

1. **Isolate the unit**: Mock all external dependencies
2. **Control the environment**: Set up precise test conditions  
3. **Test the interface**: Focus on inputs and outputs
4. **Verify behavior**: Check both results and interactions

This ensures that tests are reliable, fast, and don't affect real systems or data.

## Testing Framework

The project uses a combination of testing frameworks:

- **unittest**: Python's standard unit testing framework for test organization and assertions
- **unittest.mock**: For mocking dependencies and isolating components
- **TestClient** from FastAPI: For testing API endpoints without running an actual server
- **pytest**: For advanced test discovery and execution
- **coverage**: For code coverage analysis and reporting

## Test Structure

```
test/
├── backend/                 # Backend tests
│   ├── app/                # API endpoint tests
│   ├── services/           # Service layer tests
│   └── utils/              # Utility function tests
├── frontend/               # Frontend tests (future)
├── integration/            # Integration tests (future)
└── run_all_tests.py       # Main test runner
```

## Key Features

- 🔍 **Auto-discover test files** - Automatically finds all `test_*.py` files
- 📊 **Coverage reports** - Generates console, HTML, and XML format coverage reports
- 🔧 **Auto-install dependencies** - Automatically installs required packages if needed
- ✅ **Detailed output** - Shows the running status and results of each test
- 🚫 **Complete isolation** - No real external services are ever contacted
- ⚡ **Fast execution** - No network delays or external service processing time

## Running Tests

### Quick Start

```bash
# Run all tests with coverage
cd test
python run_all_tests.py
```

### Backend Tests

```bash
# Run backend tests only
python test/backend/run_all_test.py
```

### Individual Test Files

```bash
# Run specific test file
python -m pytest test/backend/services/test_agent_service.py -v
```

## Output Files

When tests complete, you'll find:

- `coverage_html/` - Detailed HTML format coverage report
- `coverage.xml` - XML format coverage report (for CI/CD)
- `.coverage` - Coverage data file
- Console output with detailed test results and coverage statistics

## Testing Strategy

### 1. Dependency Isolation

External modules are mocked before imports to avoid real connections:

- Database connections are mocked
- ElasticSearch and other external services are mocked
- No actual database operations are performed during tests
- HTTP clients are mocked to prevent network calls

### 2. Mock-based Testing

- HTTP requests are simulated using FastAPI's TestClient
- External service calls are intercepted with mock objects
- No actual network connections or port bindings occur
- Authentication functions are mocked to return predictable test values

### 3. Test Organization

- Tests are organized as classes inheriting from `unittest.TestCase`
- Each API endpoint or function has multiple test cases (success, failure, exception scenarios)
- Comprehensive patches are applied to isolate the code under test
- Tests follow a clear setup-execute-assert pattern

### 4. API Testing

- API endpoints are tested for correct response codes, payload structure, and error handling
- Both synchronous and asynchronous endpoints are covered
- Streaming responses are tested through specialized test cases
- Authentication and authorization are thoroughly tested

## Module Patching Technique

A critical technique used in the test suite is patching modules before they're imported. This prevents any real connections to external services.

### Example: Patching Before Import

```python
# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Setup patches for dependencies before importing modules
patches = [
    patch('botocore.client.BaseClient._make_api_call', return_value={}),
    patch('backend.database.client.MinioClient', MagicMock()),
    patch('backend.database.client.db_client', MagicMock()),
    patch('backend.utils.auth_utils.get_current_user_id', 
          MagicMock(return_value=('test_user', 'test_tenant'))),
    patch('httpx.AsyncClient', MagicMock())
]

# Start all patches
for p in patches:
    p.start()

# Now import the modules after applying all patches
from backend.apps.file_management_app import router
```

### Benefits of This Approach

1. **Complete Isolation**: No real external services are ever contacted
2. **No Side Effects**: Tests can't modify production databases or services
3. **Faster Tests**: No network delays or external service processing time
4. **Predictable Results**: Tests use controlled mock data for consistent results
5. **No Port Binding**: The FastAPI application never binds to a real network port

## Test Example

Here's a detailed example of how tests are structured:

```python
@patch("utils.auth_utils.get_current_user_id")
@patch("database.agent_db.query_all_tools")
async def test_list_tools_api_success(self, mock_query_all_tools, mock_get_current_user_id):
    # Setup
    mock_get_current_user_id.return_value = ("user123", "tenant456")
    expected_tools = [{"id": 1, "name": "Tool1"}, {"id": 2, "name": "Tool2"}]
    mock_query_all_tools.return_value = expected_tools
    
    # Execute
    result = await list_tools_api(authorization="Bearer fake_token")
    
    # Assert
    mock_get_current_user_id.assert_called_once_with("Bearer fake_token")
    mock_query_all_tools.assert_called_once_with(tenant_id="tenant456")
    self.assertEqual(result, expected_tools)
```

## Coverage Reporting

The test suite generates comprehensive coverage reports:

- **Console Output**: Line-by-line coverage details
- **HTML Report**: Detailed coverage report in `coverage_html/`
- **XML Report**: Coverage data for CI/CD integration
- **Summary Statistics**: Overall coverage percentage and missing lines

## Sample Output

```
Nexent Community - Unit Test Runner
============================================================
Discovered Test Files:
----------------------------------------
  • backend/services/test_agent_service.py
  • backend/services/test_conversation_management_service.py
  • backend/services/test_knowledge_summary_service.py

Total: 3 test files

============================================================
Running Unit Tests with Coverage
============================================================

test_get_enable_tool_id_by_agent_id ... ok
test_save_message_with_string_content ... ok
test_load_knowledge_prompts ... ok
...

============================================================
Coverage Report
============================================================
Name                                               Stmts   Miss  Cover   Missing
--------------------------------------------------------------------------------
backend/services/agent_service.py                   120     15    88%   45-50, 78-82
backend/services/conversation_management_service.py  180     25    86%   123-128, 156-162
backend/services/knowledge_summary_service.py        45      8    82%   35-42
--------------------------------------------------------------------------------
TOTAL                                               345     48    86%

HTML coverage report generated in: test/coverage_html
XML coverage report generated: test/coverage.xml

============================================================
✅ All tests passed!
```

## Dependencies

The test runner automatically installs required packages if they're not already available:

- `pytest-cov` - For pytest coverage integration
- `coverage` - For code coverage analysis
- `pytest` - For advanced test discovery and execution

## Best Practices

1. **Always mock external dependencies** before importing modules
2. **Use descriptive test names** that explain what is being tested
3. **Follow the setup-execute-assert pattern** for clear test structure
4. **Test both success and failure scenarios** for comprehensive coverage
5. **Keep tests independent** - each test should be able to run in isolation
6. **Use meaningful mock data** that represents real-world scenarios
7. **Document complex test scenarios** with clear comments

This testing framework ensures that all code changes are thoroughly validated before deployment, maintaining high code quality and reliability across the entire Nexent platform. 