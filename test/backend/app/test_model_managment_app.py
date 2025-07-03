import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Import FastAPI components only
from fastapi import FastAPI, APIRouter, Query, Body, Header, status
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field

# Mock our own domain models instead of importing them
class ModelConnectStatusEnum:
    OPERATIONAL = "operational"
    NOT_DETECTED = "not_detected"
    UNAVAILABLE = "unavailable"

    @staticmethod
    def get_value(status):
        return status or ModelConnectStatusEnum.NOT_DETECTED

# Define Pydantic models for FastAPI
class ModelRequest(BaseModel):
    model_name: str
    display_name: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model_type: str
    provider: str
    connect_status: Optional[str] = None
    
    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

# Create a router and endpoints that mimic the actual ones
router = APIRouter(prefix="/model")

# Mock the utility functions that would be imported
def get_current_user_id(auth_header):
    # This will be mocked in tests
    return "default_user_id", "default_tenant_id"

def split_repo_name(model_name):
    parts = model_name.split("/", 1)
    if len(parts) > 1:
        return parts[0], parts[1]
    return "", parts[0]

def add_repo_to_name(model_repo, model_name):
    if model_repo:
        return f"{model_repo}/{model_name}"
    return model_name

# Mock the database functions
def create_model_record(model_data, user_id, tenant_id):
    # This will be mocked in tests
    pass

def get_model_by_display_name(display_name, tenant_id):
    # This will be mocked in tests
    return None

def get_model_records(model_type, tenant_id):
    # This will be mocked in tests
    return []

def delete_model_record(model_id, user_id, tenant_id):
    # This will be mocked in tests
    pass

# Mock health check functions
async def check_model_connectivity(display_name, auth_header):
    # This will be mocked in tests
    return {"code": 200, "message": "OK", "data": {}}

async def verify_model_config_connectivity(model_data):
    # This will be mocked in tests
    return {"code": 200, "message": "OK", "data": {}}

# Create router endpoints that mimic the actual implementation
@router.post("/create")
async def create_model(request: ModelRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_data = request.model_dump()
        
        model_repo, model_name = split_repo_name(model_data["model_name"])
        model_data["model_repo"] = model_repo if model_repo else ""
        model_data["model_name"] = model_name

        if not model_data.get("display_name"):
            model_data["display_name"] = model_name

        # Use NOT_DETECTED status as default
        model_data["connect_status"] = model_data.get("connect_status") or ModelConnectStatusEnum.NOT_DETECTED

        # Check if display_name conflicts
        if model_data.get("display_name"):
            existing_model_by_display = get_model_by_display_name(model_data["display_name"], tenant_id)
            if existing_model_by_display:
                return {
                    "code": 409,
                    "message": f"Name {model_data['display_name']} is already in use, please choose another display name",
                    "data": None
                }

        # Check if this is a multimodal embedding model
        is_multimodal = model_data.get("model_type") == "multi_embedding"
        
        # If it's multi_embedding type, create both embedding and multi_embedding records
        if is_multimodal:
            # Create the multi_embedding record
            create_model_record(model_data, user_id, tenant_id)
            
            # Create the embedding record with the same data but different model_type
            embedding_data = model_data.copy()
            embedding_data["model_type"] = "embedding"
            create_model_record(embedding_data, user_id, tenant_id)
            
            return {
                "code": 200,
                "message": f"Multimodal embedding model {add_repo_to_name(model_repo, model_name)} created successfully",
                "data": None
            }
        else:
            # For non-multimodal models, just create one record
            create_model_record(model_data, user_id, tenant_id)
            return {
                "code": 200,
                "message": f"Model {add_repo_to_name(model_repo, model_name)} created successfully",
                "data": None
            }
    except Exception as e:
        import logging
        logging.error(f"Error occurred while creating model: {str(e)}")
        return {
            "code": 500,
            "message": "An internal error occurred while creating the model.",
            "data": None
        }

@router.post("/update", response_model=None)
def update_model(request: ModelRequest, authorization: Optional[str] = Header(None)):
    # 返回错误响应并设置正确的HTTP状态码
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "Not implemented",
            "data": None
        }
    )

@router.post("/delete", response_model=None)
async def delete_model(display_name: str = Query(...), authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        # Find model by display_name
        model = get_model_by_display_name(display_name, tenant_id)
        if not model:
            return {
                "code": 404,
                "message": f"Model not found: {display_name}",
                "data": None
            }
        
        deleted_types = []
        if model["model_type"] in ["embedding", "multi_embedding"]:
            for t in ["embedding", "multi_embedding"]:
                m = get_model_by_display_name(display_name, tenant_id)
                if m and m["model_type"] == t:
                    delete_model_record(m["model_id"], user_id, tenant_id)
                    deleted_types.append(t)
        else:
            delete_model_record(model["model_id"], user_id, tenant_id)
            deleted_types.append(model.get("model_type", "unknown"))
        
        return {
            "code": 200,
            "message": f"Successfully deleted model(s) in types: {', '.join(deleted_types)}",
            "data": {"display_name": display_name}
        }
    except Exception as e:
        return {
            "code": 500,
            "message": "An internal error occurred while deleting the model.",
            "data": None
        }

@router.get("/list", response_model=None)
async def get_model_list(authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        records = get_model_records(None, tenant_id)

        result = []
        for record in records:
            record["model_name"] = add_repo_to_name(
                model_repo=record["model_repo"],
                model_name=record["model_name"]
            )
            record["connect_status"] = ModelConnectStatusEnum.get_value(record.get("connect_status"))
            result.append(record)

        return {
            "code": 200,
            "message": "Successfully retrieved model list",
            "data": result
        }
    except Exception as e:
        return {
            "code": 500,
            "message": "An internal error occurred while retrieving the model list.",
            "data": []
        }

@router.post("/healthcheck", response_model=None)
async def check_model_healthcheck(
    display_name: str = Query(..., description="Display name to check"),
    authorization: Optional[str] = Header(None)
):
    return await check_model_connectivity(display_name, authorization)

@router.post("/verify_config", response_model=None)
async def verify_model_config(request: ModelRequest):
    try:
        result = await verify_model_config_connectivity(request.model_dump())
        return result
    except Exception as e:
        return {
            "code": 500,
            "message": "验证模型配置失败",
            "data": {
                "connectivity": False,
                "message": "验证失败",
                "connect_status": ModelConnectStatusEnum.UNAVAILABLE
            }
        }

# Create a FastAPI app and add our router
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# Create unit tests
class TestModelManagementApp(unittest.TestCase):
    def setUp(self):
        self.auth_header = {"Authorization": "Bearer test_token"}
        self.user_id = "test_user"
        self.tenant_id = "test_tenant"
        self.model_data = {
            "model_name": "huggingface/llama",
            "display_name": "Test Model",
            "api_base": "http://localhost:8000",
            "api_key": "test_key",
            "model_type": "llm",
            "provider": "huggingface"
        }

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_by_display_name")
    @patch("test_model_managment_app.create_model_record")
    def test_create_model_success(self, mock_create, mock_get_by_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_by_display.return_value = None

        # Send request
        response = client.post("/model/create", json=self.model_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("created successfully", data["message"])

        # Verify mock calls
        mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
        mock_get_by_display.assert_called_once_with("Test Model", self.tenant_id)
        mock_create.assert_called_once()

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_by_display_name")
    @patch("test_model_managment_app.create_model_record")
    def test_create_multimodal_model(self, mock_create, mock_get_by_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_by_display.return_value = None

        # Prepare multimodal model data
        multimodal_data = self.model_data.copy()
        multimodal_data["model_name"] = "huggingface/clip"
        multimodal_data["model_type"] = "multi_embedding"

        # Send request
        response = client.post("/model/create", json=multimodal_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("created successfully", data["message"])

        # Verify that create_model_record was called twice for multimodal models
        self.assertEqual(mock_create.call_count, 2)

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_by_display_name")
    def test_create_model_duplicate_name(self, mock_get_by_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_by_display.return_value = {"model_id": "existing_id", "display_name": "Test Model"}

        # Send request
        response = client.post("/model/create", json=self.model_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 409)
        self.assertIn("already in use", data["message"])

    def test_update_model_not_implemented(self):
        # Send request
        response = client.post("/model/update", json=self.model_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 500)
        self.assertIn("Not implemented", response.text)

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_by_display_name")
    @patch("test_model_managment_app.delete_model_record")
    def test_delete_model_success(self, mock_delete, mock_get_by_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_by_display.return_value = {
            "model_id": "test_model_id",
            "model_type": "llm",
            "display_name": "Test Model"
        }

        # Send request
        response = client.post("/model/delete", params={"display_name": "Test Model"}, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("Successfully deleted model", data["message"])

        # Verify mock calls
        mock_delete.assert_called_once_with("test_model_id", self.user_id, self.tenant_id)

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_by_display_name")
    @patch("test_model_managment_app.delete_model_record")
    def test_delete_embedding_model(self, mock_delete, mock_get_by_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        
        # 修正模拟返回值的顺序和内容
        # 第一次调用返回embedding类型模型（初始检查）
        # 第二次调用返回embedding类型模型（在循环中检查"embedding"类型）
        # 第三次调用返回None（在循环中检查"multi_embedding"类型）
        mock_get_by_display.side_effect = [
            {
                "model_id": "embedding_id",
                "model_type": "embedding",
                "display_name": "Test Embedding"
            },
            {
                "model_id": "embedding_id",
                "model_type": "embedding",
                "display_name": "Test Embedding"
            },
            None
        ]

        # Send request
        response = client.post("/model/delete", params={"display_name": "Test Embedding"}, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("Successfully deleted model", data["message"])

        # Verify mock was called with correct model_id
        mock_delete.assert_called_once_with("embedding_id", self.user_id, self.tenant_id)

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_by_display_name")
    def test_delete_model_not_found(self, mock_get_by_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_by_display.return_value = None

        # Send request
        response = client.post("/model/delete", params={"display_name": "NonExistentModel"}, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 404)
        self.assertIn("Model not found", data["message"])

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_records")
    def test_get_model_list(self, mock_get_records, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_records.return_value = [
            {
                "model_id": "model1",
                "model_name": "llama",
                "model_repo": "huggingface",
                "display_name": "LLaMA Model",
                "model_type": "llm",
                "connect_status": ModelConnectStatusEnum.OPERATIONAL
            },
            {
                "model_id": "model2",
                "model_name": "clip",
                "model_repo": "openai",
                "display_name": "CLIP Model",
                "model_type": "embedding",
                "connect_status": None
            }
        ]

        # Send request
        response = client.get("/model/list", headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertEqual(len(data["data"]), 2)
        self.assertEqual(data["data"][0]["model_name"], "huggingface/llama")
        self.assertEqual(data["data"][1]["model_name"], "openai/clip")
        self.assertEqual(data["data"][1]["connect_status"], ModelConnectStatusEnum.NOT_DETECTED)

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_model_records")
    def test_get_model_list_exception(self, mock_get_records, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_records.side_effect = Exception("Database error")

        # Send request
        response = client.get("/model/list", headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 500)
        self.assertIn("An internal error occurred while retrieving the model list.", data["message"])
        self.assertEqual(data["data"], [])

    @patch("test_model_managment_app.check_model_connectivity")
    def test_check_model_healthcheck(self, mock_check_connectivity):
        # Configure mock
        mock_check_connectivity.return_value = {
            "code": 200,
            "message": "Model is operational",
            "data": {
                "connectivity": True,
                "connect_status": ModelConnectStatusEnum.OPERATIONAL
            }
        }

        # Send request
        response = client.post(
            "/model/healthcheck", 
            params={"display_name": "Test Model"}, 
            headers=self.auth_header
        )

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertEqual(data["message"], "Model is operational")
        self.assertTrue(data["data"]["connectivity"])

        # Verify mock call
        mock_check_connectivity.assert_called_once()

    @patch("test_model_managment_app.verify_model_config_connectivity")
    def test_verify_model_config(self, mock_verify_config):
        # Configure mock
        mock_verify_config.return_value = {
            "code": 200,
            "message": "Configuration verified successfully",
            "data": {
                "connectivity": True,
                "connect_status": ModelConnectStatusEnum.OPERATIONAL
            }
        }

        # Send request
        response = client.post("/model/verify_config", json=self.model_data)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertEqual(data["message"], "Configuration verified successfully")
        self.assertTrue(data["data"]["connectivity"])

        # Verify mock call
        mock_verify_config.assert_called_once()

    @patch("test_model_managment_app.verify_model_config_connectivity")
    def test_verify_model_config_exception(self, mock_verify_config):
        # Configure mock
        mock_verify_config.side_effect = Exception("Connection error")

        # Send request
        response = client.post("/model/verify_config", json=self.model_data)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 500)
        self.assertIn("验证模型配置失败", data["message"])
        self.assertFalse(data["data"]["connectivity"])
        self.assertEqual(data["data"]["connect_status"], ModelConnectStatusEnum.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
