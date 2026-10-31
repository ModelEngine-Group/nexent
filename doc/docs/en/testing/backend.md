# Backend Testing

This guide covers the comprehensive backend testing framework used in Nexent, including API testing, service layer testing, and utility function testing.

## Test Structure

The backend tests are organized in the following structure:

```
test/backend/
├── adapters/              # Adapter tests (e.g., jiuwen_sdk_adapter)
├── agents/                # Agent core tests
│   ├── test_agent_run_manager.py
│   ├── test_create_agent_info.py
│   ├── test_nl2agent_agent.py
│   └── test_preprocess_manager.py
├── app/                   # API endpoint tests
│   ├── test_agent_app.py
│   ├── test_conversation_management_app.py
│   ├── test_data_process_app.py
│   ├── test_file_management_app.py
│   ├── test_image_app.py
│   ├── test_knowledge_summary_app.py
│   ├── test_model_managment_app.py
│   ├── test_northbound_app.py
│   ├── test_prompt_app.py
│   ├── test_remote_mcp_app.py
│   └── ...
├── apps/                  # Supplementary API tests
│   ├── test_memory_dreaming_app.py
│   └── test_memory_record_app.py
├── consts/                # Constants and model tests
├── data_process/          # Data processing tests (Ray, Celery tasks)
├── database/              # Database access layer tests
├── middleware/            # Middleware tests
├── permissions/           # Permission (RBAC/DAC) tests
├── services/              # Service layer tests
│   ├── test_agent_service.py
│   ├── test_agent_version_service.py
│   ├── test_conversation_management_service.py
│   ├── test_data_process_service.py
│   ├── test_file_management_service.py
│   ├── test_image_service.py
│   ├── test_knowledge_summary_service.py
│   ├── test_memory_config_service.py
│   ├── test_model_management_service.py
│   ├── test_prompt_service.py
│   ├── test_remote_mcp_service.py
│   └── ...
├── utils/                 # Utility function tests
│   ├── test_langchain_utils.py
│   ├── test_llm_utils.py
│   └── test_prompt_template_utils.py
└── test_*.py              # Root-level integration-style tests (LLM integration, runtime services, etc.)
```

## Running Backend Tests

### Complete Backend Test Suite

```bash
# After activating the backend virtual environment, run all tests (with coverage) from the project root
source backend/.venv/bin/activate
python test/run_all_test.py

# Run backend tests only
NEXENT_PYTEST_TARGETS=test/backend python test/run_all_test.py
```

### Individual Test Categories

```bash
# Run all API tests
python -m pytest test/backend/app/ -v

# Run all service tests
python -m pytest test/backend/services/ -v

# Run all utility tests
python -m pytest test/backend/utils/ -v
```

### Specific Test Files

```bash
# Run specific API test
python -m pytest test/backend/app/test_agent_app.py -v

# Run specific service test
python -m pytest test/backend/services/test_agent_service.py -v

# Run specific utility test
python -m pytest test/backend/utils/test_langchain_utils.py -v
```

## API Testing

API tests use FastAPI's TestClient to simulate HTTP requests without running an actual server.

### Test Setup Pattern

```python
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

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

# Import modules after applying patches
from apps.agent_app import agent_config_router, agent_runtime_router

# Create test app
app = FastAPI()
app.include_router(agent_config_router)
app.include_router(agent_runtime_router)
client = TestClient(app)
```

### API Test Example

The following example is adapted from the real `test/backend/app/test_agent_app.py`. Patches must be applied to the **module where the name is referenced** (e.g., `apps.agent_app.get_current_user_id`), not where the function is originally defined (`backend.utils.auth_utils.get_current_user_id`); async service functions that are `await`ed must be mocked with `AsyncMock`:

```python
from unittest.mock import AsyncMock


def test_search_agent_info_api_success(mocker):
    """Test successful agent info query"""
    # Setup - mock authentication and the service layer return value
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {"agent_id": 123, "name": "Test Agent"}

    # Execute
    response = client.post(
        "/agent/search_info",
        json={"agent_id": 123},
        headers={"Authorization": "Bearer test_token"}
    )

    # Assert
    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with("Bearer test_token")
    # Falls back to the authenticated tenant ID when tenant_id is not provided; version_no defaults to 0
    mock_get_agent_info.assert_called_once_with(123, "auth_tenant_id", 0, "user_id")
    assert response.json()["agent_id"] == 123
    assert response.json()["name"] == "Test Agent"
```

## Service Layer Testing

Service layer tests focus on business logic and data processing without HTTP overhead.

### Service Test Pattern

The following example is adapted from the real `test/backend/services/test_agent_service.py`. `get_agent_id_by_name` internally calls `search_agent_id_by_agent_name`, which is imported from `backend.database.agent_db` into the service module's namespace, so the patch target is `backend.services.agent_service.search_agent_id_by_agent_name` (the module where the name is referenced):

```python
import pytest
from unittest.mock import patch

from services.agent_service import get_agent_id_by_name


@pytest.mark.asyncio
@patch("backend.services.agent_service.search_agent_id_by_agent_name")
async def test_get_agent_id_by_name(mock_search):
    """Test resolving an agent ID by name and tenant"""
    # Test the success path
    mock_search.return_value = 1
    result = await get_agent_id_by_name("test_agent", "test_tenant")
    assert result == 1
    mock_search.assert_called_once_with("test_agent", "test_tenant")

    # Test the not-found path
    mock_search.side_effect = Exception("Not found")
    with pytest.raises(Exception, match="agent not found"):
        await get_agent_id_by_name("test_agent", "test_tenant")
```

### Mocking Database Operations

Functions in the `backend/database/` layer obtain sessions through the `get_db_session()` context manager. In tests, this function can be replaced with a mock session to isolate the real database (the following example is based on the real `search_agent_id_by_agent_name`):

```python
import pytest
from unittest.mock import MagicMock

from database.agent_db import search_agent_id_by_agent_name


def test_search_agent_id_by_agent_name(mocker):
    """Test querying an agent ID by name and tenant"""
    # Setup - mock the session context and the query().filter().first() chain
    session = MagicMock()
    session.__enter__.return_value = session
    mocker.patch("database.agent_db.get_db_session", return_value=session)
    mock_agent = MagicMock()
    mock_agent.agent_id = 100
    session.query.return_value = session
    session.filter.return_value = session
    session.first.return_value = mock_agent

    # Execute
    result = search_agent_id_by_agent_name("Test Agent", "tenant456")

    # Assert
    assert result == 100
    session.query.assert_called_once()


def test_search_agent_id_by_agent_name_not_found(mocker):
    """Test that a ValueError is raised when not found"""
    # Setup - the query returns no result
    session = MagicMock()
    session.__enter__.return_value = session
    mocker.patch("database.agent_db.get_db_session", return_value=session)
    session.query.return_value = session
    session.filter.return_value = session
    session.first.return_value = None

    # Execute & Assert
    with pytest.raises(ValueError, match="agent not found"):
        search_agent_id_by_agent_name("Missing Agent", "tenant456")
```

## Utility Function Testing

Utility functions are tested in isolation with mocked dependencies.

### Utility Test Example

```python
from unittest.mock import MagicMock, patch

from utils.langchain_utils import discover_langchain_modules


def test_discover_langchain_modules():
    # Setup - mock the module scan to avoid loading real langchain dependencies
    with patch("utils.langchain_utils._is_langchain_tool", return_value=True) as mock_check:
        # Execute
        tools = discover_langchain_modules("some_package")

        # Assert
        mock_check.assert_called()
        assert isinstance(tools, list)
```

## Testing Asynchronous Code

Backend tests handle both synchronous and asynchronous code. `test/pytest.ini` sets `asyncio_mode = auto`, so async test functions are automatically detected and executed (explicit `@pytest.mark.asyncio` markers are also supported):

### Async Test Pattern

Async functions that are `await`ed must be mocked with `AsyncMock` — the return value of an `AsyncMock` is the result of the `await` expression (this usage matches the real `new_callable=AsyncMock` in `test/backend/app/test_agent_app.py`):

```python
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_async_operation():
    """Demonstrate mocking an awaited async function with AsyncMock"""
    # Setup - the return value of AsyncMock is the result of the await expression
    mock_async_query = AsyncMock(return_value={"result": "success"})

    # Execute
    result = await mock_async_query()

    # Assert
    assert result["result"] == "success"
    mock_async_query.assert_awaited_once()
```

## Error Handling Tests

Comprehensive error handling is tested. `search_agent_info_api` catches all exceptions and maps them to HTTP 500; the following example verifies that a service-layer exception is correctly converted into an error response:

```python
from unittest.mock import AsyncMock


def test_search_agent_info_api_error(mocker):
    """Test API error responses (service layer exception → HTTP 500)"""
    # Setup - mock authentication and an exception-raising service layer
    mocker.patch("apps.agent_app.get_current_user_id",
                 return_value=("user_id", "auth_tenant_id"))
    mocker.patch(
        "apps.agent_app.get_agent_info_impl",
        new_callable=AsyncMock,
        side_effect=Exception("Database error"),
    )

    # Execute
    response = client.post(
        "/agent/search_info",
        json={"agent_id": 123},
        headers={"Authorization": "Bearer test_token"}
    )

    # Assert - search_agent_info_api catches the exception and returns 500
    assert response.status_code == 500
    assert response.json() == {"detail": "Agent search info error."}
```

## Authentication and Authorization Tests

Security-related functionality is thoroughly tested:

### Authentication Failure → 401

Internal northbound endpoints (the `agent_runtime_router`, which shares the `/agent` prefix) validate the internal JWT via `verify_internal_runtime_jwt` and map failures to 401. The example is adapted from the real `test/backend/app/test_agent_app.py`:

```python
from consts.exceptions import UnauthorizedError


def test_authentication_required(mocker):
    """Test that endpoints requiring an internal JWT return 401"""
    # Setup - mock the internal runtime JWT validation to fail
    mocker.patch(
        "apps.agent_app.verify_internal_runtime_jwt",
        side_effect=UnauthorizedError("Invalid internal runtime token"),
    )

    # Execute - access the northbound stop endpoint
    response = client.post(
        "/agent/internal/northbound/stop/123",
        headers={"Authorization": "Bearer invalid"}
    )

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid internal runtime token"
```

### Tenant Isolation

`/agent/search_info` supports an explicit `tenant_id` query parameter. The example is adapted from the real `test_search_agent_info_api_with_explicit_tenant_id`, verifying that the explicit tenant overrides the authenticated tenant and is passed to the service layer:

```python
from unittest.mock import AsyncMock


def test_tenant_isolation(mocker):
    """Test that an explicitly provided tenant_id overrides the authenticated tenant"""
    # Setup - the authenticated tenant differs from the explicit tenant
    mock_get_user_id = mocker.patch("apps.agent_app.get_current_user_id")
    mock_get_agent_info = mocker.patch(
        "apps.agent_app.get_agent_info_impl", new_callable=AsyncMock)
    mock_get_user_id.return_value = ("user_id", "auth_tenant_id")
    mock_get_agent_info.return_value = {
        "agent_id": 456, "name": "Test Agent with Explicit Tenant",
    }

    # Execute - explicitly pass the tenant_id query parameter
    response = client.post(
        "/agent/search_info",
        json={"agent_id": 456},
        params={"tenant_id": "explicit_tenant_789"},
        headers={"Authorization": "Bearer test_token"}
    )

    # Assert - the service layer receives the explicit tenant, not the authenticated one
    assert response.status_code == 200
    mock_get_agent_info.assert_called_once_with(
        456, "explicit_tenant_789", 0, "user_id")
```

## Coverage Analysis

Backend tests generate detailed coverage reports:

### Coverage Commands

```bash
# Generate coverage report
python -m pytest test/backend/ --cov=backend --cov-report=html --cov-report=xml

# View coverage in terminal
python -m pytest test/backend/ --cov=backend --cov-report=term-missing
```

### Coverage Targets

- **API Endpoints**: 90%+ coverage
- **Service Layer**: 85%+ coverage  
- **Utility Functions**: 80%+ coverage
- **Error Handling**: 100% coverage for critical paths

## Test Data Management

### Fixtures and Test Data

```python
import pytest


@pytest.fixture
def test_agent():
    """Set up test data"""
    return {
        "id": 1,
        "name": "Test Agent",
        "description": "A test agent",
        "system_prompt": "You are a test agent"
    }


@pytest.fixture
def test_user():
    """Mock user and tenant information"""
    return ("user123", "tenant456")

def test_with_fixtures(test_agent, test_user):
    """Inject fixtures directly into the test function"""
    assert test_agent["id"] == 1
    assert test_user == ("user123", "tenant456")
```

## Performance Testing

Backend tests include performance considerations:

```python
def test_get_agent_by_name_response_time(mocker):
    """Test that API responses are within acceptable time limits"""
    import time

    # Setup - mock authentication and the query-by-name logic to avoid real database calls
    mocker.patch("apps.agent_app.get_current_user_id",
                 return_value=("user_id", "auth_tenant_id"))
    mocker.patch("apps.agent_app.get_agent_by_name_impl",
                 return_value={"agent_id": 1, "latest_version_no": 0})

    start_time = time.time()
    response = client.get(
        "/agent/by-name/TestAgent",
        headers={"Authorization": "Bearer test_token"}
    )
    end_time = time.time()

    # Assert response time is under 100ms
    assert end_time - start_time < 0.1
    assert response.status_code == 200
```

## Best Practices for Backend Testing

1. **Mock External Dependencies**: Always mock database, external APIs, and services
2. **Test Both Success and Failure**: Cover all possible code paths
3. **Use Descriptive Test Names**: Make it clear what each test validates
4. **Keep Tests Independent**: Each test should run in isolation
5. **Test Edge Cases**: Include boundary conditions and error scenarios
6. **Maintain Test Data**: Use consistent, realistic test data
7. **Document Complex Tests**: Add comments for complex test scenarios
8. **Regular Coverage Reviews**: Monitor and improve coverage over time

This comprehensive backend testing framework ensures that all backend functionality is thoroughly validated before deployment, maintaining high code quality and reliability. 