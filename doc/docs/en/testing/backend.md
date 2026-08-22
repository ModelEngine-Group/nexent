# Backend Testing

This guide covers the comprehensive backend testing framework used in Nexent, including API testing, service layer testing, and utility function testing.

## Test Structure

The backend tests are organized in the following structure:

```
test/backend/
├── app/                    # API endpoint tests
│   ├── test_agent_app.py
│   ├── test_base_app.py
│   ├── test_config_sync_app.py
│   ├── test_conversation_management_app.py
│   ├── test_data_process_app.py
│   ├── test_elasticsearch_app.py
│   ├── test_file_management_app.py
│   ├── test_image_app.py
│   ├── test_knowledge_app.py
│   ├── test_knowledge_summary_app.py
│   ├── test_me_model_managment_app.py
│   ├── test_model_managment_app.py
│   ├── test_prompt_app.py
│   └── test_remote_mcp_app.py
├── services/              # Service layer tests
│   ├── test_agent_service.py
│   ├── test_conversation_management_service.py
│   ├── test_data_process_service.py
│   ├── test_elasticsearch_service.py
│   ├── test_file_management_service.py
│   ├── test_image_service.py
│   ├── test_knowledge_service.py
│   ├── test_knowledge_summary_service.py
│   ├── test_model_management_service.py
│   ├── test_prompt_service.py
│   └── test_remote_mcp_service.py
├── utils/                 # Utility function tests
│   ├── test_langchain_utils.py
│   └── test_prompt_template_utils.py
└── run_all_test.py       # Backend test runner
```

## Running Backend Tests

### Complete Backend Test Suite

```bash
# From project root
python test/backend/run_all_test.py

# From test/backend directory
cd test/backend
python run_all_test.py
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
from backend.apps.agent_app import router

# Create test app
app = FastAPI()
app.include_router(router)
client = TestClient(app)
```

### API Test Example

```python
class TestAgentApp(unittest.TestCase):
    
    def setUp(self):
        # Setup test client and common mocks
        pass
    
    def test_create_agent_success(self):
        """Test successful agent creation"""
        # Setup
        agent_data = {
            "name": "Test Agent",
            "description": "A test agent",
            "system_prompt": "You are a test agent"
        }
        
        # Execute
        response = client.post("/agents", json=agent_data)
        
        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json())
        self.assertEqual(response.json()["name"], "Test Agent")
    
    def test_create_agent_invalid_data(self):
        """Test agent creation with invalid data"""
        # Setup
        invalid_data = {"name": ""}  # Missing required fields
        
        # Execute
        response = client.post("/agents", json=invalid_data)
        
        # Assert
        self.assertEqual(response.status_code, 422)  # Validation error
```

## Service Layer Testing

Service layer tests focus on business logic and data processing without HTTP overhead.

### Service Test Pattern

```python
class TestAgentService(unittest.TestCase):
    
    @patch("backend.database.agent_db.save_agent")
    @patch("backend.utils.auth_utils.get_current_user_id")
    async def test_create_agent_success(self, mock_get_user, mock_save_agent):
        # Setup
        mock_get_user.return_value = ("user123", "tenant456")
        mock_save_agent.return_value = {"id": 1, "name": "Test Agent"}
        
        # Execute
        result = await create_agent(
            name="Test Agent",
            description="A test agent",
            system_prompt="You are a test agent"
        )
        
        # Assert
        mock_save_agent.assert_called_once()
        self.assertEqual(result["name"], "Test Agent")
        self.assertIn("id", result)
```

### Mocking Database Operations

```python
@patch("backend.database.agent_db.query_agent_by_id")
@patch("backend.database.agent_db.update_agent")
async def test_update_agent_success(self, mock_update, mock_query):
    # Setup
    mock_query.return_value = {"id": 1, "name": "Old Name"}
    mock_update.return_value = {"id": 1, "name": "New Name"}
    
    # Execute
    result = await update_agent(agent_id=1, name="New Name")
    
    # Assert
    mock_update.assert_called_once_with(agent_id=1, name="New Name")
    self.assertEqual(result["name"], "New Name")
```

## Utility Function Testing

Utility functions are tested in isolation with mocked dependencies.

### Utility Test Example

```python
class TestLangchainUtils(unittest.TestCase):
    
    @patch("langchain.llms.openai.OpenAI")
    def test_create_llm_instance(self, mock_openai):
        # Setup
        mock_openai.return_value = MagicMock()
        
        # Execute
        llm = create_llm_instance(model_name="gpt-3.5-turbo")
        
        # Assert
        mock_openai.assert_called_once()
        self.assertIsNotNone(llm)
```

## Testing Asynchronous Code

Backend tests handle both synchronous and asynchronous code:

### Async Test Pattern

```python
class TestAsyncService(unittest.TestCase):
    
    @patch("backend.database.agent_db.async_query")
    async def test_async_operation(self, mock_async_query):
        # Setup
        mock_async_query.return_value = {"result": "success"}
        
        # Execute
        result = await async_operation()
        
        # Assert
        self.assertEqual(result["result"], "success")
        mock_async_query.assert_called_once()
```

## Error Handling Tests

Comprehensive error handling is tested:

```python
def test_api_error_handling(self):
    """Test API error responses"""
    # Setup - mock service to raise exception
    with patch('backend.services.agent_service.create_agent') as mock_service:
        mock_service.side_effect = Exception("Database error")
        
        # Execute
        response = client.post("/agents", json={"name": "Test"})
        
        # Assert
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.json())
```

## Authentication and Authorization Tests

Security-related functionality is thoroughly tested:

```python
def test_authentication_required(self):
    """Test that endpoints require authentication"""
    # Execute without auth header
    response = client.get("/agents")
    
    # Assert
    self.assertEqual(response.status_code, 401)

def test_tenant_isolation(self):
    """Test that users can only access their tenant's data"""
    # Setup - mock auth to return different tenant
    with patch('backend.utils.auth_utils.get_current_user_id') as mock_auth:
        mock_auth.return_value = ("user1", "tenant1")
        
        # Execute
        response = client.get("/agents")
        
        # Assert - verify tenant filtering is applied
        # This would check that the service layer filters by tenant
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
class TestWithFixtures(unittest.TestCase):
    
    def setUp(self):
        """Set up test data and mocks"""
        self.test_agent = {
            "id": 1,
            "name": "Test Agent",
            "description": "A test agent",
            "system_prompt": "You are a test agent"
        }
        
        self.test_user = ("user123", "tenant456")
    
    def tearDown(self):
        """Clean up after tests"""
        # Reset any global state if needed
        pass
```

## Performance Testing

Backend tests include performance considerations:

```python
def test_api_response_time(self):
    """Test that API responses are within acceptable time limits"""
    import time
    
    start_time = time.time()
    response = client.get("/agents")
    end_time = time.time()
    
    # Assert response time is under 100ms
    self.assertLess(end_time - start_time, 0.1)
    self.assertEqual(response.status_code, 200)
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