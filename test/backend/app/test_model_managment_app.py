import unittest
import pytest
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
    DETECTING = "detecting"
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

class ModelResponse(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None

class BatchCreateModelsRequest(BaseModel):
    models: List[Dict[str, Any]]
    api_key: Optional[str] = None
    max_tokens: Optional[int] = None
    provider: str
    type: str

class ProviderModelRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model_type: Optional[str] = None

# Create a router and endpoints that mimic the actual ones
router = APIRouter(prefix="/model")

# Mock the utility functions that would be imported
def get_current_user_id(auth_header):
    # This will be mocked in tests
    return "default_user_id", "default_tenant_id"

SILICON_BASE_URL = "http://silicon.test"

async def prepare_model_dict(**kwargs):
    # Mocked function
    pass

async def get_models_from_silicon(model_data):
    # This will be mocked in tests
    return []

def split_repo_name(model_name):
    parts = model_name.split("/", 1)
    if len(parts) > 1:
        return parts[0], parts[1]
    return "", parts[0]

def add_repo_to_name(model_repo, model_name):
    if model_repo:
        return f"{model_repo}/{model_name}"
    return model_name

def get_models_by_tenant_factory_type(tenant_id, provider, model_type):
    # This will be mocked in tests
    return []

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

def update_model_record(model_id, model_data, user_id):
    # This will be mocked in tests
    pass

def split_display_name(model_name):
    # This will be mocked in tests
    return model_name

# Mock health check functions
async def check_model_connectivity(display_name, auth_header):
    # This will be mocked in tests
    return {"code": 200, "message": "OK", "data": {}}

async def verify_model_config_connectivity(model_data):
    # This will be mocked in tests
    return {"code": 200, "message": "OK", "data": {}}

# Create router endpoints that mimic the actual implementation
@router.post("/create")
@pytest.mark.asyncio
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

@router.post("/update_single_model", response_model=ModelResponse)
async def update_single_model(request: dict, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_data = request
        if not model_data.get("display_name"):
            model_data["display_name"] = split_display_name(model_data["model_name"])
            # Check if display_name conflicts
            existing_model_by_display = get_model_by_display_name(model_data["display_name"], tenant_id)
            if existing_model_by_display and existing_model_by_display["model_id"] != model_data["model_id"]:
                return ModelResponse(
                    code=409,
                    message=f"Name {model_data['display_name']} is already in use, please choose another display name",
                    data=None
                )
        model_repo, model_name = split_repo_name(model_data["model_name"])
        model_data["model_repo"] = model_repo
        model_data["model_name"] = model_name
        update_model_record(model_data["model_id"], model_data, user_id)
        return ModelResponse(
            code=200,
            message=f"Model {model_data['model_name']} updated successfully",
            data=None
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to update model: {str(e)}",
            data=None
        )

@router.post("/batch_create_models", response_model=ModelResponse)
@pytest.mark.asyncio
async def batch_create_models(request: BatchCreateModelsRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_list = request.models
        model_api_key = request.api_key
        max_tokens = request.max_tokens
        if request.provider == "silicon":
            model_url = SILICON_BASE_URL
        else:
            model_url = ""
        existing_model_list = get_models_by_tenant_factory_type(tenant_id, request.provider, request.type)
        model_list_ids = {model.get('id') for model in model_list} if model_list else set()
        # delete existing model
        for model in existing_model_list:
            model["display_name"] = model["model_repo"] + "/" + model["model_name"]
            if model["display_name"] not in model_list_ids:
                delete_model_record(model["model_id"], user_id, tenant_id)
        # create new model
        for model in model_list:
            model_repo, model_name = split_repo_name(model["id"])
            if model_name:
                existing_model_by_display = get_model_by_display_name(request.provider + "/" + model_name, tenant_id)
                if existing_model_by_display:
                    # Check if max_tokens has changed
                    existing_max_tokens = existing_model_by_display.get("max_tokens", 4096)
                    new_max_tokens = model.get("max_tokens", 4096)
                    if existing_max_tokens == new_max_tokens:
                        continue

            model_dict = await prepare_model_dict(
                provider=request.provider,
                model=model,
                model_url=model_url,
                model_api_key=model_api_key,
                max_tokens=max_tokens
            )
            create_model_record(model_dict, user_id, tenant_id)
        
        return ModelResponse(
            code=200,
            message=f"Batch create models successfully",
            data=None
        )
    except Exception as e:
        import logging
        logging.error(f"Failed to batch create models: {str(e)}")
        return ModelResponse(
            code=500,
            message=f"Failed to batch create models: {str(e)}",
            data=None
        )

@router.post("/create_provider", response_model=ModelResponse)
async def create_provider_model(request: ProviderModelRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_data = request.model_dump()
        model_list=[]
        existing_model_list=[]
        
        if model_data["provider"] == "silicon":
            model_list = await get_models_from_silicon(model_data)

        if request.model_type != "embedding" and request.model_type != "multi_embedding":
            existing_model_list = get_models_by_tenant_factory_type(tenant_id, request.provider, request.model_type)
            
            # 检查existing_model_list中的模型是否在model_list中，如果在，就添加max_tokens属性
            if model_list and existing_model_list:
                # 创建existing_model_list的模型ID集合，用于快速查找
                existing_model_ids = set()
                for existing_model in existing_model_list:
                    model_full_name = existing_model["model_repo"] + "/" + existing_model["model_name"]
                    existing_model_ids.add(model_full_name)
                
                # 遍历model_list，如果模型在existing_model_list中，添加max_tokens属性
                for model in model_list:
                    if model.get("id") in existing_model_ids:
                        # 找到对应的existing_model，获取其max_tokens值
                        for existing_model in existing_model_list:
                            model_full_name = existing_model["model_repo"] + "/" + existing_model["model_name"]
                            if model.get("id") == model_full_name:
                                model["max_tokens"] = existing_model.get("max_tokens")
                                break
        # Sort by the first letter of id in ascending order
        if isinstance(model_list, list):
            model_list.sort(key=lambda m: str((m.get("id") if isinstance(m, dict) else m) or "")[:1].lower(), reverse=False)
        return ModelResponse(
            code=200,
            message=f"Provider model {model_data['provider']} created successfully",
            data=model_list
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to create provider model: {str(e)}",
            data=None
        )

@router.post("/delete", response_model=None)
@pytest.mark.asyncio
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
@pytest.mark.asyncio
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
@pytest.mark.asyncio
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

@router.post("/provider/list")
@pytest.mark.asyncio
async def get_provider_list(request: dict, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        provider = request.get("provider")
        model_type = request.get("model_type")
        model_list = get_models_by_tenant_factory_type(tenant_id, provider, model_type)
        for model in model_list:
            model["id"] = model["model_repo"] + "/" + model["model_name"]
        return {
            "code": 200,
            "message": f"Provider model {provider} created successfully",
            "data": model_list
        }
    except Exception as e:
        return {
            "code": 500,
            "message": f"Failed to get provider list: {str(e)}",
            "data": None
        }

# Create a FastAPI app and add our router
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# Remove direct top-level import of backend router to avoid side-effects on import
# and provide a safe builder that stubs S3 before importing the backend module.
import sys
import importlib
from typing import Tuple

def _build_backend_client_with_s3_stub() -> Tuple[TestClient, object]:
    class _FakeS3Client:
        def head_bucket(self, Bucket=None, **kwargs):
            return None
        def create_bucket(self, Bucket=None, **kwargs):
            return None
        def upload_file(self, *args, **kwargs):
            return None
        def upload_fileobj(self, *args, **kwargs):
            return None
        def download_file(self, *args, **kwargs):
            return None
        def generate_presigned_url(self, *args, **kwargs):
            return "http://example.com"
        def head_object(self, *args, **kwargs):
            return {"ContentLength": "0"}
        def list_objects_v2(self, *args, **kwargs):
            return {}
        def delete_object(self, *args, **kwargs):
            return None
        def get_object(self, *args, **kwargs):
            return {"Body": b""}

    def _fake_boto3_client(service_name, *args, **kwargs):
        return _FakeS3Client()

    with patch("boto3.client", new=_fake_boto3_client):
        # Ensure modules are not already imported to avoid side-effects before patching
        for m in [
            "backend.apps.model_managment_app",
            "backend.database.model_management_db",
            "backend.database.client",
        ]:
            if m in sys.modules:
                del sys.modules[m]

        # Inject stub modules required by backend.apps.model_managment_app
        import types as _types
        from enum import Enum as _Enum
        from pydantic import BaseModel as _BaseModel

        # consts.model
        consts_mod = _types.ModuleType("consts")
        consts_model_mod = _types.ModuleType("consts.model")
        class _ModelConnectStatusEnum(_Enum):
            OPERATIONAL = "operational"
            NOT_DETECTED = "not_detected"
            DETECTING = "detecting"
            UNAVAILABLE = "unavailable"
            @staticmethod
            def get_value(status):
                return status or _ModelConnectStatusEnum.NOT_DETECTED.value
        class _ModelResponse(_BaseModel):
            code: int
            message: str
            data: Optional[Any] = None
        class _ModelRequest(_BaseModel):
            model_name: str
            display_name: Optional[str] = None
            base_url: Optional[str] = None
            api_key: Optional[str] = None
            model_type: str
            provider: str
            connect_status: Optional[str] = None
        class _BatchCreateModelsRequest(_BaseModel):
            models: List[Dict[str, Any]]
            api_key: Optional[str] = None
            max_tokens: Optional[int] = None
            provider: str
            type: str
        class _ProviderModelRequest(_BaseModel):
            provider: str
            model_type: Optional[str] = None
            api_key: Optional[str] = None
        consts_model_mod.ModelConnectStatusEnum = _ModelConnectStatusEnum
        consts_model_mod.ModelResponse = _ModelResponse
        consts_model_mod.ModelRequest = _ModelRequest
        consts_model_mod.BatchCreateModelsRequest = _BatchCreateModelsRequest
        consts_model_mod.ProviderModelRequest = _ProviderModelRequest

        # consts.provider
        consts_provider_mod = _types.ModuleType("consts.provider")
        class _ProviderEnum(_Enum):
            SILICON = "silicon"
        consts_provider_mod.ProviderEnum = _ProviderEnum
        consts_provider_mod.SILICON_BASE_URL = "http://silicon.test"

        sys.modules["consts"] = consts_mod
        sys.modules["consts.model"] = consts_model_mod
        sys.modules["consts.provider"] = consts_provider_mod

        # database.model_management_db
        database_mod = _types.ModuleType("database")
        database_mm_mod = _types.ModuleType("database.model_management_db")
        def _noop(*args, **kwargs):
            return None
        def _get_model_records(*args, **kwargs):
            return []
        def _get_model_by_name(*args, **kwargs):
            return None
        database_mm_mod.create_model_record = _noop
        database_mm_mod.delete_model_record = _noop
        database_mm_mod.get_model_records = _get_model_records
        database_mm_mod.get_model_by_display_name = _noop
        database_mm_mod.get_models_by_tenant_factory_type = _get_model_records
        database_mm_mod.update_model_record = _noop
        database_mm_mod.get_model_by_name = _get_model_by_name
        sys.modules["database"] = database_mod
        sys.modules["database.model_management_db"] = database_mm_mod

        # services.model_health_service
        services_mod = _types.ModuleType("services")
        services_health_mod = _types.ModuleType("services.model_health_service")
        async def _check_model_connectivity(*args, **kwargs):
            return {"code": 200, "message": "OK", "data": {}}
        async def _embedding_dimension_check(model_data):
            return 0
        async def _verify_model_config_connectivity(*args, **kwargs):
            return {"code": 200, "message": "OK", "data": {"connectivity": True}}
        services_health_mod.check_model_connectivity = _check_model_connectivity
        services_health_mod.embedding_dimension_check = _embedding_dimension_check
        services_health_mod.verify_model_config_connectivity = _verify_model_config_connectivity

        # services.model_provider_service
        services_provider_mod = _types.ModuleType("services.model_provider_service")
        class _SiliconModelProvider:
            async def get_models(self, model_data):
                return []
        async def _prepare_model_dict(**kwargs):
            return {}
        services_provider_mod.SiliconModelProvider = _SiliconModelProvider
        services_provider_mod.prepare_model_dict = _prepare_model_dict

        sys.modules["services"] = services_mod
        sys.modules["services.model_health_service"] = services_health_mod
        sys.modules["services.model_provider_service"] = services_provider_mod

        # utils.auth_utils and utils.model_name_utils
        utils_mod = _types.ModuleType("utils")
        utils_auth_mod = _types.ModuleType("utils.auth_utils")
        utils_name_mod = _types.ModuleType("utils.model_name_utils")
        def _get_current_user_id(auth_header):
            return ("default_user_id", "default_tenant_id")
        def _split_repo_name(model_name: str):
            parts = model_name.split("/", 1)
            if len(parts) > 1:
                return parts[0], parts[1]
            return "", parts[0]
        def _add_repo_to_name(model_repo, model_name):
            return f"{model_repo}/{model_name}" if model_repo else model_name
        def _split_display_name(model_name):
            return model_name.split("/")[-1]
        utils_auth_mod.get_current_user_id = _get_current_user_id
        utils_name_mod.split_repo_name = _split_repo_name
        utils_name_mod.add_repo_to_name = _add_repo_to_name
        utils_name_mod.split_display_name = _split_display_name
        sys.modules["utils"] = utils_mod
        sys.modules["utils.auth_utils"] = utils_auth_mod
        sys.modules["utils.model_name_utils"] = utils_name_mod

        backend_model_app = importlib.import_module("backend.apps.model_managment_app")
        backend_app = FastAPI()
        backend_app.include_router(backend_model_app.router)
        backend_client_local = TestClient(backend_app)
        return backend_client_local, backend_model_app

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

    @patch("test_model_managment_app.create_model_record")
    @patch("test_model_managment_app.prepare_model_dict", new_callable=AsyncMock)
    @patch("test_model_managment_app.get_model_by_display_name")
    @patch("test_model_managment_app.delete_model_record")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    @patch("test_model_managment_app.get_current_user_id")
    def test_batch_create_models_success(self, mock_get_user, mock_get_existing, mock_delete, mock_get_by_display, mock_prepare, mock_create):
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {"model_id": "delete_me_id", "model_repo": "test_provider", "model_name": "to_be_deleted"},
            {"model_id": "keep_me_id", "model_repo": "test_provider", "model_name": "to_be_kept_and_skipped"},
        ]
        
        request_models = [
            {"id": "test_provider/new_model"},
            {"id": "test_provider/to_be_kept_and_skipped"},
        ]

        def get_by_display_name_side_effect(display_name, tenant_id):
            if display_name == "test_provider/new_model":
                return None
            if display_name == "test_provider/to_be_kept_and_skipped":
                return {"model_id": "keep_me_id"}
            return None
        mock_get_by_display.side_effect = get_by_display_name_side_effect
        mock_prepare.return_value = {"prepared": "data"}

        request_data = {
            "models": request_models,
            "provider": "test_provider",
            "type": "llm",
            "api_key": "test_key"
        }

        response = client.post("/model/batch_create_models", json=request_data, headers=self.auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("Batch create models successfully", data["message"])
        mock_get_existing.assert_called_once_with(self.tenant_id, "test_provider", "llm")
        mock_delete.assert_called_once_with("delete_me_id", self.user_id, self.tenant_id)
        mock_create.assert_called_once_with({"prepared": "data"}, self.user_id, self.tenant_id)
        self.assertEqual(mock_get_by_display.call_count, 2)
        mock_prepare.assert_called_once()


    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    @patch("test_model_managment_app.get_current_user_id")
    def test_batch_create_models_exception(self, mock_get_user, mock_get_existing):
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.side_effect = Exception("Database connection error")
        request_data = {
            "models": [{"id": "provider/new_model"}],
            "provider": "test_provider",
            "type": "llm"
        }

        response = client.post("/model/batch_create_models", json=request_data, headers=self.auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 500)
        self.assertIn("Failed to batch create models: Database connection error", data["message"])

    @patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock)
    @patch("test_model_managment_app.get_current_user_id")
    def test_create_provider_model_silicon_success(self, mock_get_user, mock_get_silicon):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_silicon.return_value = [{"id": "silicon/model1"}]
        request_data = {"provider": "silicon", "api_key": "test_key"}

        response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("Provider model silicon created successfully", data["message"])
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["id"], "silicon/model1")
        mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
        mock_get_silicon.assert_called_once()

    @patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock)
    @patch("test_model_managment_app.get_current_user_id")
    def test_create_provider_model_exception(self, mock_get_user, mock_get_silicon):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_silicon.side_effect = Exception("Silicon API error")
        request_data = {"provider": "silicon", "api_key": "test_key"}

        response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 500)
        self.assertIn("Failed to create provider model: Silicon API error", data["message"])
        mock_get_user.assert_called_once_with(self.auth_header["Authorization"])

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models(self, mock_get_existing, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "model1",
                "max_tokens": 4096
            },
            {
                "model_repo": "silicon", 
                "model_name": "model2",
                "max_tokens": 8192
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model1"},
                {"id": "silicon/model2"},
                {"id": "silicon/new_model"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"  # Not embedding or multi_embedding
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that max_tokens were merged for existing models
            result_models = data["data"]
            self.assertEqual(len(result_models), 3)
            
            # Find models with max_tokens (existing models)
            model1 = next((m for m in result_models if m["id"] == "silicon/model1"), None)
            model2 = next((m for m in result_models if m["id"] == "silicon/model2"), None)
            new_model = next((m for m in result_models if m["id"] == "silicon/new_model"), None)
            
            self.assertIsNotNone(model1)
            self.assertEqual(model1.get("max_tokens"), 4096)
            self.assertIsNotNone(model2)
            self.assertEqual(model2.get("max_tokens"), 8192)
            self.assertIsNotNone(new_model)
            self.assertNotIn("max_tokens", new_model)  # New model shouldn't have max_tokens
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_none_max_tokens(self, mock_get_existing, mock_get_user):
        """Test when existing model has None max_tokens"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "model_with_none_tokens",
                "max_tokens": None  # None max_tokens
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model_with_none_tokens"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that model gets None max_tokens
            result_models = data["data"]
            self.assertEqual(len(result_models), 1)
            
            model = result_models[0]
            self.assertEqual(model["id"], "silicon/model_with_none_tokens")
            self.assertIsNone(model.get("max_tokens"))
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_missing_max_tokens_field(self, mock_get_existing, mock_get_user):
        """Test when existing model doesn't have max_tokens field"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "model_without_tokens_field"
                # No max_tokens field
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model_without_tokens_field"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that model gets None max_tokens (default behavior when field is missing)
            result_models = data["data"]
            self.assertEqual(len(result_models), 1)
            
            model = result_models[0]
            self.assertEqual(model["id"], "silicon/model_without_tokens_field")
            self.assertIsNone(model.get("max_tokens"))
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_missing_model_repo(self, mock_get_existing, mock_get_user):
        """Test when existing model has missing model_repo field"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_name": "model_without_repo",
                "max_tokens": 4096
                # Missing model_repo field
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "model_without_repo"}  # No repo prefix
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 500)  # Should return 500 when model_repo is missing
            self.assertIn("Failed to create provider model", data["message"])
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_missing_model_name(self, mock_get_existing, mock_get_user):
        """Test when existing model has missing model_name field"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "max_tokens": 4096
                # Missing model_name field
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/"}  # Empty model name
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 500)  # Should return 500 when model_name is missing
            self.assertIn("Failed to create provider model", data["message"])
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_multiple_matches(self, mock_get_existing, mock_get_user):
        """Test when multiple existing models match the same provider model"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "duplicate_model",
                "max_tokens": 4096
            },
            {
                "model_repo": "silicon",
                "model_name": "duplicate_model",  # Duplicate model
                "max_tokens": 8192  # Different max_tokens
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/duplicate_model"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that model gets max_tokens from the first match (4096)
            result_models = data["data"]
            self.assertEqual(len(result_models), 1)
            
            model = result_models[0]
            self.assertEqual(model["id"], "silicon/duplicate_model")
            self.assertEqual(model.get("max_tokens"), 4096)  # First match
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_case_sensitive_matching(self, mock_get_existing, mock_get_user):
        """Test case sensitivity in model ID matching"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "Silicon",  # Different case
                "model_name": "Model1",   # Different case
                "max_tokens": 4096
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model1"}  # Different case
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that model doesn't get max_tokens due to case mismatch
            result_models = data["data"]
            self.assertEqual(len(result_models), 1)
            
            model = result_models[0]
            self.assertEqual(model["id"], "silicon/model1")
            self.assertNotIn("max_tokens", model)  # No match due to case difference
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_empty_string_fields(self, mock_get_existing, mock_get_user):
        """Test when existing model has empty string fields"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "",  # Empty string
                "model_name": "model1",
                "max_tokens": 4096
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "/model1"}  # With leading slash when repo is empty
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that model gets max_tokens with empty repo
            result_models = data["data"]
            self.assertEqual(len(result_models), 1)
            
            model = result_models[0]
            self.assertEqual(model["id"], "/model1")
            self.assertEqual(model.get("max_tokens"), 4096)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_zero_max_tokens(self, mock_get_existing, mock_get_user):
        """Test when existing model has zero max_tokens"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "model_with_zero_tokens",
                "max_tokens": 0  # Zero max_tokens
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model_with_zero_tokens"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that model gets zero max_tokens
            result_models = data["data"]
            self.assertEqual(len(result_models), 1)
            
            model = result_models[0]
            self.assertEqual(model["id"], "silicon/model_with_zero_tokens")
            self.assertEqual(model.get("max_tokens"), 0)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_negative_max_tokens(self, mock_get_existing, mock_get_user):
        """Test when existing model has negative max_tokens"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "model_with_negative_tokens",
                "max_tokens": -1  # Negative max_tokens
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model_with_negative_tokens"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that model gets negative max_tokens
            result_models = data["data"]
            self.assertEqual(len(result_models), 1)
            
            model = result_models[0]
            self.assertEqual(model["id"], "silicon/model_with_negative_tokens")
            self.assertEqual(model.get("max_tokens"), -1)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    def test_create_provider_model_embedding_type_skips_existing_check(self, mock_get_user):
        """Test that embedding type skips existing model check"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/embedding_model"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "embedding"  # This should skip existing model check
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Should not call get_models_by_tenant_factory_type for embedding types
            # The test verifies this by not mocking get_models_by_tenant_factory_type
            # and ensuring no error occurs

    @patch("test_model_managment_app.get_current_user_id")
    def test_create_provider_model_multi_embedding_type_skips_existing_check(self, mock_get_user):
        """Test that multi_embedding type skips existing model check"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/multi_embedding_model"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "multi_embedding"  # This should skip existing model check
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Should not call get_models_by_tenant_factory_type for multi_embedding types
            # The test verifies this by not mocking get_models_by_tenant_factory_type
            # and ensuring no error occurs

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_no_overlap(self, mock_get_existing, mock_get_user):
        """Test when existing models don't overlap with new models from provider"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "existing_model",
                "max_tokens": 4096
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/new_model1"},
                {"id": "silicon/new_model2"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that new models don't have max_tokens since they don't exist in existing models
            result_models = data["data"]
            self.assertEqual(len(result_models), 2)
            
            for model in result_models:
                self.assertNotIn("max_tokens", model)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_partial_overlap(self, mock_get_existing, mock_get_user):
        """Test when some existing models overlap with new models from provider"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "overlapping_model",
                "max_tokens": 4096
            },
            {
                "model_repo": "silicon",
                "model_name": "non_overlapping_model", 
                "max_tokens": 8192
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/overlapping_model"},  # This should get max_tokens
                {"id": "silicon/new_model"}  # This should not get max_tokens
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that only overlapping model has max_tokens
            result_models = data["data"]
            self.assertEqual(len(result_models), 2)
            
            overlapping_model = next((m for m in result_models if m["id"] == "silicon/overlapping_model"), None)
            new_model = next((m for m in result_models if m["id"] == "silicon/new_model"), None)
            
            self.assertIsNotNone(overlapping_model)
            self.assertEqual(overlapping_model.get("max_tokens"), 4096)
            self.assertIsNotNone(new_model)
            self.assertNotIn("max_tokens", new_model)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_empty_provider_list(self, mock_get_existing, mock_get_user):
        """Test when provider returns empty list but there are existing models"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "existing_model",
                "max_tokens": 4096
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = []  # Empty list from provider
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that empty list is returned
            result_models = data["data"]
            self.assertEqual(len(result_models), 0)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_empty_existing_list(self, mock_get_existing, mock_get_user):
        """Test when there are no existing models but provider returns models"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = []  # No existing models
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/new_model1"},
                {"id": "silicon/new_model2"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that new models don't have max_tokens since there are no existing models
            result_models = data["data"]
            self.assertEqual(len(result_models), 2)
            
            for model in result_models:
                self.assertNotIn("max_tokens", model)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_optimized_lookup(self, mock_get_existing, mock_get_user):
        """Test the optimized lookup using existing_model_map dictionary"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "model1",
                "max_tokens": 4096
            },
            {
                "model_repo": "silicon",
                "model_name": "model2", 
                "max_tokens": 8192
            },
            {
                "model_repo": "silicon",
                "model_name": "model3",
                "max_tokens": 16384
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model1"},
                {"id": "silicon/model2"},
                {"id": "silicon/model3"},
                {"id": "silicon/new_model"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that all existing models get their max_tokens properly merged
            result_models = data["data"]
            self.assertEqual(len(result_models), 4)
            
            # Verify the optimized lookup worked correctly
            model1 = next((m for m in result_models if m["id"] == "silicon/model1"), None)
            model2 = next((m for m in result_models if m["id"] == "silicon/model2"), None)
            model3 = next((m for m in result_models if m["id"] == "silicon/model3"), None)
            new_model = next((m for m in result_models if m["id"] == "silicon/new_model"), None)
            
            self.assertIsNotNone(model1)
            self.assertEqual(model1.get("max_tokens"), 4096)
            self.assertIsNotNone(model2)
            self.assertEqual(model2.get("max_tokens"), 8192)
            self.assertIsNotNone(model3)
            self.assertEqual(model3.get("max_tokens"), 16384)
            self.assertIsNotNone(new_model)
            self.assertNotIn("max_tokens", new_model)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_create_provider_model_with_existing_models_edge_cases(self, mock_get_existing, mock_get_user):
        """Test edge cases in the existing model lookup logic"""
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_existing.return_value = [
            {
                "model_repo": "silicon",
                "model_name": "model_with_special_chars",
                "max_tokens": 4096
            },
            {
                "model_repo": "silicon",
                "model_name": "model_with_numbers_123",
                "max_tokens": 8192
            },
            {
                "model_repo": "silicon",
                "model_name": "MODEL_WITH_UPPERCASE",
                "max_tokens": 16384
            }
        ]
        
        # Mock the get_models_from_silicon function
        with patch("test_model_managment_app.get_models_from_silicon", new_callable=AsyncMock) as mock_get_silicon:
            mock_get_silicon.return_value = [
                {"id": "silicon/model_with_special_chars"},
                {"id": "silicon/model_with_numbers_123"},
                {"id": "silicon/MODEL_WITH_UPPERCASE"},
                {"id": "silicon/unknown_model"}
            ]
            
            request_data = {
                "provider": "silicon", 
                "api_key": "test_key",
                "model_type": "llm"
            }
            
            response = client.post("/model/create_provider", json=request_data, headers=self.auth_header)
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["code"], 200)
            self.assertIn("Provider model silicon created successfully", data["message"])
            
            # Check that edge cases are handled correctly
            result_models = data["data"]
            self.assertEqual(len(result_models), 4)
            
            # Verify special characters, numbers, and case sensitivity
            special_model = next((m for m in result_models if m["id"] == "silicon/model_with_special_chars"), None)
            number_model = next((m for m in result_models if m["id"] == "silicon/model_with_numbers_123"), None)
            uppercase_model = next((m for m in result_models if m["id"] == "silicon/MODEL_WITH_UPPERCASE"), None)
            unknown_model = next((m for m in result_models if m["id"] == "silicon/unknown_model"), None)
            
            self.assertIsNotNone(special_model)
            self.assertEqual(special_model.get("max_tokens"), 4096)
            self.assertIsNotNone(number_model)
            self.assertEqual(number_model.get("max_tokens"), 8192)
            self.assertIsNotNone(uppercase_model)
            self.assertEqual(uppercase_model.get("max_tokens"), 16384)
            self.assertIsNotNone(unknown_model)
            self.assertNotIn("max_tokens", unknown_model)
            
            mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
            mock_get_existing.assert_called_once_with(self.tenant_id, "silicon", "llm")

    def test_create_provider_model_silicon_success_backend(self):
        backend_client_local, backend_model_app = _build_backend_client_with_s3_stub()
        with patch.object(backend_model_app, "get_current_user_id", return_value=(self.user_id, self.tenant_id)):
            with patch.object(backend_model_app.SiliconModelProvider, "get_models", new=AsyncMock(return_value=[{"id": "b2"}, {"id": "A1"}, {"id": "a0"}, {"id": "c3"}])) as mock_get:
                request_data = {"provider": "silicon", "api_key": "test_key"}
                response = backend_client_local.post("/model/create_provider", json=request_data, headers=self.auth_header)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["code"], 200)
                self.assertIn("Provider model silicon created successfully", data["message"])
                # Check that models are sorted by first letter in ascending order
                self.assertEqual([m["id"] for m in data["data"]], ["A1", "a0", "b2", "c3"])
                mock_get.assert_called_once()

    def test_create_provider_model_exception_backend(self):
        backend_client_local, backend_model_app = _build_backend_client_with_s3_stub()
        with patch.object(backend_model_app, "get_current_user_id", return_value=(self.user_id, self.tenant_id)):
            with patch.object(backend_model_app.SiliconModelProvider, "get_models", new=AsyncMock(side_effect=Exception("Silicon API error"))) as mock_get:
                request_data = {"provider": "silicon", "api_key": "test_key"}
                response = backend_client_local.post("/model/create_provider", json=request_data, headers=self.auth_header)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["code"], 500)
                self.assertIn("Failed to create provider model: Silicon API error", data["message"])
                mock_get.assert_called_once()

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

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_get_provider_list(self, mock_get_models, mock_get_user):
        # 配置 mock
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_models.return_value = [
            {
                "model_repo": "huggingface",
                "model_name": "llama",
                "model_type": "llm"
            },
            {
                "model_repo": "openai",
                "model_name": "clip",
                "model_type": "embedding"
            }
        ]
        request_data = {
            "provider": "huggingface",
            "model_type": "llm",
            "api_key": "test_key"
        }
        response = client.post("/model/provider/list", json=request_data, headers=self.auth_header)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("created successfully", data["message"])
        self.assertEqual(len(data["data"]), 2)
        self.assertEqual(data["data"][0]["id"], "huggingface/llama")
        self.assertEqual(data["data"][1]["id"], "openai/clip")

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.get_models_by_tenant_factory_type")
    def test_get_provider_list_exception(self, mock_get_models, mock_get_user):
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_get_models.side_effect = Exception("DB error")
        request_data = {
            "provider": "huggingface",
            "model_type": "llm",
            "api_key": "test_key"
        }
        response = client.post("/model/provider/list", json=request_data, headers=self.auth_header)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 500)
        self.assertIn("Failed to get provider list", data["message"])

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.split_display_name")
    @patch("test_model_managment_app.get_model_by_display_name")
    @patch("test_model_managment_app.update_model_record")
    def test_update_single_model_success(self, mock_update, mock_get_by_display, mock_split_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_split_display.return_value = "Test Model"
        mock_get_by_display.return_value = None

        # Prepare update request data
        update_data = {
            "model_id": "test_model_id",
            "model_name": "huggingface/llama",
            "display_name": "Updated Test Model",
            "api_base": "http://localhost:8001",
            "api_key": "updated_key",
            "model_type": "llm",
            "provider": "huggingface"
        }

        # Send request
        response = client.post("/model/update_single_model", json=update_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("updated successfully", data["message"])

        # Verify mock calls
        mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
        
        # The endpoint modifies the data by splitting model_name and adding model_repo
        # So we need to verify the actual modified data that gets passed to update_model_record
        expected_data = update_data.copy()
        expected_data["model_repo"] = "huggingface"
        expected_data["model_name"] = "llama"
        
        mock_update.assert_called_once_with("test_model_id", expected_data, self.user_id)

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.split_display_name")
    @patch("test_model_managment_app.get_model_by_display_name")
    @patch("test_model_managment_app.update_model_record")
    def test_update_single_model_without_display_name(self, mock_update, mock_get_by_display, mock_split_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_split_display.return_value = "Auto Generated Name"
        mock_get_by_display.return_value = None

        # Prepare update request data without display_name
        update_data = {
            "model_id": "test_model_id",
            "model_name": "huggingface/llama",
            "api_base": "http://localhost:8001",
            "api_key": "updated_key",
            "model_type": "llm",
            "provider": "huggingface"
        }

        # Send request
        response = client.post("/model/update_single_model", json=update_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("updated successfully", data["message"])

        # Verify mock calls
        mock_split_display.assert_called_once_with("huggingface/llama")
        mock_get_by_display.assert_called_once_with("Auto Generated Name", self.tenant_id)
        mock_update.assert_called_once()

    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.split_display_name")
    @patch("test_model_managment_app.get_model_by_display_name")
    def test_update_single_model_display_name_conflict(self, mock_get_by_display, mock_split_display, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_split_display.return_value = "Conflicting Name"
        mock_get_by_display.return_value = {
            "model_id": "other_model_id",
            "display_name": "Conflicting Name"
        }

        # Prepare update request data
        update_data = {
            "model_id": "test_model_id",
            "model_name": "huggingface/llama",
            "api_base": "http://localhost:8001",
            "api_key": "updated_key",
            "model_type": "llm",
            "provider": "huggingface"
        }

        # Send request
        response = client.post("/model/update_single_model", json=update_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 409)
        self.assertIn("already in use", data["message"])

        # Verify mock calls
        mock_split_display.assert_called_once_with("huggingface/llama")
        mock_get_by_display.assert_called_once_with("Conflicting Name", self.tenant_id)


    @patch("test_model_managment_app.get_current_user_id")
    @patch("test_model_managment_app.update_model_record")
    def test_update_single_model_exception(self, mock_update, mock_get_user):
        # Configure mocks
        mock_get_user.return_value = (self.user_id, self.tenant_id)
        mock_update.side_effect = Exception("Database update error")

        # Prepare update request data
        update_data = {
            "model_id": "test_model_id",
            "model_name": "huggingface/llama",
            "display_name": "Test Model",
            "api_base": "http://localhost:8001",
            "api_key": "updated_key",
            "model_type": "llm",
            "provider": "huggingface"
        }

        # Send request
        response = client.post("/model/update_single_model", json=update_data, headers=self.auth_header)

        # Assert response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], 500)
        self.assertIn("Failed to update model: Database update error", data["message"])

        # Verify mock calls
        mock_update.assert_called_once()

    def test_batch_update_models_success_backend(self):
        backend_client_local, backend_model_app = _build_backend_client_with_s3_stub()
        with patch.object(backend_model_app, "get_current_user_id", return_value=(self.user_id, self.tenant_id)):
            with patch.object(backend_model_app, "update_model_record") as mock_update:
                models = [
                    {"model_id": "id1", "api_key": "k1", "max_tokens": 100},
                    {"model_id": "id2", "api_key": "k2", "max_tokens": 200},
                ]
                response = backend_client_local.post("/model/batch_update_models", json=models, headers=self.auth_header)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["code"], 200)
                self.assertIn("Batch update models successfully", data["message"])
                self.assertEqual(mock_update.call_count, 2)
                mock_update.assert_any_call("id1", models[0], self.user_id)
                mock_update.assert_any_call("id2", models[1], self.user_id)

    def test_batch_update_models_exception_backend(self):
        backend_client_local, backend_model_app = _build_backend_client_with_s3_stub()
        with patch.object(backend_model_app, "get_current_user_id", return_value=(self.user_id, self.tenant_id)):
            with patch.object(backend_model_app, "update_model_record", side_effect=Exception("Update failed")) as mock_update:
                models = [
                    {"model_id": "id1", "api_key": "k1"}
                ]
                response = backend_client_local.post("/model/batch_update_models", json=models, headers=self.auth_header)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["code"], 500)
                self.assertIn("Failed to batch update models: Update failed", data["message"]) 


    def test_batch_update_models_empty_list_backend(self):
        backend_client_local, backend_model_app = _build_backend_client_with_s3_stub()
        with patch.object(backend_model_app, "get_current_user_id", return_value=(self.user_id, self.tenant_id)) as mock_get_user:
            with patch.object(backend_model_app, "update_model_record") as mock_update:
                models = []
                response = backend_client_local.post("/model/batch_update_models", json=models, headers=self.auth_header)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["code"], 200)
                self.assertIn("Batch update models successfully", data["message"]) 
                mock_get_user.assert_called_once_with(self.auth_header["Authorization"])
                mock_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()