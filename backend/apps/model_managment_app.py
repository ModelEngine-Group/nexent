import logging
from typing import Optional, List

from fastapi import Query, APIRouter, Header

from consts.model import ModelConnectStatusEnum, ModelResponse, ModelRequest, ProviderModelRequest, \
    BatchCreateModelsRequest
from consts.provider import SILICON_BASE_URL, ProviderEnum
from database.model_management_db import create_model_record, delete_model_record, \
    get_model_records, get_model_by_display_name, get_models_by_tenant_factory_type
from database.model_management_db import update_model_record
from services.model_health_service import check_model_connectivity, embedding_dimension_check
from services.model_provider_service import SiliconModelProvider, prepare_model_dict
from utils.auth_utils import get_current_user_id
from utils.model_name_utils import split_repo_name, add_repo_to_name, split_display_name

router = APIRouter(prefix="/model")
logger = logging.getLogger("model_management_app")


@router.post("/create", response_model=ModelResponse)
async def create_model(request: ModelRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        logger.info(f"Start to create model, user_id: {user_id}, tenant_id: {tenant_id}")
        model_data = request.model_dump()
        # Replace localhost with host.docker.internal for local llm
        model_base_url = model_data.get("base_url", "")
        if "localhost" in model_base_url or "127.0.0.1" in model_base_url:
            model_data["base_url"] = model_base_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
        # Split model_name
        model_repo, model_name = split_repo_name(model_data["model_name"])
        # Ensure model_repo is empty string instead of null
        model_data["model_repo"] = model_repo if model_repo else ""
        model_data["model_name"] = model_name

        if not model_data.get("display_name"):
            model_data["display_name"] = split_display_name(model_data["model_name"])

        # Use NOT_DETECTED status as default
        model_data["connect_status"] = model_data.get("connect_status") or ModelConnectStatusEnum.NOT_DETECTED.value

        # Check if display_name conflicts
        if model_data.get("display_name"):
            existing_model_by_display = get_model_by_display_name(model_data["display_name"], tenant_id)
            if existing_model_by_display:
                return ModelResponse(
                    code=409,
                    message=f"Name {model_data['display_name']} is already in use, please choose another display name",
                    data=None
                )

        if model_data.get("model_type") == "embedding" or model_data.get("model_type") == "multi_embedding":
            model_data["max_tokens"] = await embedding_dimension_check(model_data)

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
            
            return ModelResponse(
                code=200,
                message=f"Multimodal embedding model {add_repo_to_name(model_repo, model_name)} created successfully",
                data=None
            )
        else:
            # For non-multimodal models, just create one record
            create_model_record(model_data, user_id, tenant_id)
            return ModelResponse(
                code=200,
                message=f"Model {add_repo_to_name(model_repo, model_name)} created successfully",
                data=None
            )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to create model: {str(e)}",
            data=None
        )

@router.post("/create_provider", response_model=ModelResponse)
async def create_provider_model(request: ProviderModelRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_data = request.model_dump()
        model_list=[]
        
        if model_data["provider"] == ProviderEnum.SILICON.value:
            provider = SiliconModelProvider()
            model_list = await provider.get_models(model_data)

        if request.model_type != "embedding" or request.model_type != "multi_embedding":
            existing_model_list = get_models_by_tenant_factory_type(tenant_id, request.provider, request.model_type)
            
            # Check if models in existing_model_list exist in model_list, if so, add max_tokens attribute
            if model_list and existing_model_list:
                # Create a mapping of model full names to existing models for fast lookup
                existing_model_map = {}
                for existing_model in existing_model_list:
                    model_full_name = existing_model["model_repo"] + "/" + existing_model["model_name"]
                    existing_model_map[model_full_name] = existing_model
                
                # Iterate through model_list, if model exists in existing_model_list, add max_tokens attribute
                for model in model_list:
                    if model.get("id") in existing_model_map:
                        model["max_tokens"] = existing_model_map[model.get("id")].get("max_tokens")
        # Sort by the first letter of id in descending order
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


@router.post("/batch_create_models", response_model=ModelResponse)
async def batch_create_models(request: BatchCreateModelsRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_list = request.models
        model_api_key = request.api_key
        if request.provider == ProviderEnum.SILICON.value:
            model_url = SILICON_BASE_URL
        else:
            model_url = ""
        existing_model_list = get_models_by_tenant_factory_type(tenant_id, request.provider, request.type)
        model_list_ids = {model.get('id') for model in model_list} if model_list else set()
        # delete existing model
        for model in existing_model_list:
            model_full_name = model["model_repo"] + "/" + model["model_name"]
            if model_full_name not in model_list_ids:
                delete_model_record(model["model_id"], user_id, tenant_id)
        # create new model
        for model in model_list:
            model_repo, model_name = split_repo_name(model["id"])
            model_display_name = split_display_name(model["id"])
            if model_name:
                existing_model_by_display = get_model_by_display_name(request.provider + "/" + model_display_name, tenant_id)
                if existing_model_by_display:
                    # Check if max_tokens has changed
                    existing_max_tokens = existing_model_by_display["max_tokens"]
                    new_max_tokens = model["max_tokens"]
                    if existing_max_tokens != new_max_tokens:
                        update_model_record(existing_model_by_display["model_id"], {"max_tokens": new_max_tokens}, user_id)
                    continue

            model_dict = await prepare_model_dict(
                provider=request.provider,
                model=model,
                model_url=model_url,
                model_api_key=model_api_key
            )
            create_model_record(model_dict, user_id, tenant_id)

        return ModelResponse(
            code=200,
            message=f"Batch create models successfully",
            data=None
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to batch create models: {str(e)}",
            data=None
        )


@router.post("/provider/list", response_model=ModelResponse )
async def get_provider_list(request: ProviderModelRequest, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        provider = request.provider
        model_type = request.model_type
        model_list = get_models_by_tenant_factory_type(tenant_id, provider, model_type)
        for model in model_list:
            model["id"] = model["model_repo"] + "/" + model["model_name"]
        return ModelResponse(
            code=200,
            message=f"Provider model {provider} created successfully",
            data=model_list
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to get provider list: {str(e)}",
            data=None
        )


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
        model_data["model_repo"], model_data["model_name"] = split_repo_name(model_data["model_name"])
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


@router.post("/batch_update_models", response_model=ModelResponse)
async def batch_update_models(request: List[dict], authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_list = request
        for model in model_list:
            update_model_record(model["model_id"], model, user_id)
        return ModelResponse(
            code=200,
            message=f"Batch update models successfully",
            data=None
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to batch update models: {str(e)}",
            data=None
        )


@router.post("/delete", response_model=ModelResponse)
async def delete_model(display_name: str = Query(..., embed=True), authorization: Optional[str] = Header(None)):
    """
    Soft delete the specified model by display_name
    If the model is an embedding or multi_embedding type, both types will be deleted

    Args:
        display_name: Display name of the model to delete (唯一键)
        authorization: Authorization header
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        logger.info(f"Start to delete model, user_id: {user_id}, tenant_id: {tenant_id}")
        # Find model by display_name
        model = get_model_by_display_name(display_name, tenant_id)
        if not model:
            return ModelResponse(
                code=404,
                message=f"Model not found: {display_name}",
                data=None
            )
        # 支持 embedding/multi_embedding 互删
        deleted_types = []
        if model["model_type"] in ["embedding", "multi_embedding"]:
            # 查找所有 embedding/multi_embedding 且 display_name 相同的模型
            for t in ["embedding", "multi_embedding"]:
                m = get_model_by_display_name(display_name, tenant_id)
                if m and m["model_type"] == t:
                    delete_model_record(m["model_id"], user_id, tenant_id)
                    deleted_types.append(t)
        else:
            delete_model_record(model["model_id"], user_id, tenant_id)
            deleted_types.append(model.get("model_type", "unknown"))

        return ModelResponse(
            code=200,
            message=f"Successfully deleted model(s) in types: {', '.join(deleted_types)}",
            data={"display_name": display_name}
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to delete model: {str(e)}",
            data=None
        )


@router.get("/list", response_model=ModelResponse)
async def get_model_list(authorization: Optional[str] = Header(None)):
    """
    Get detailed information for all models
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        logger.info(f"Start to list models, user_id: {user_id}, tenant_id: {tenant_id}")
        records = get_model_records(None, tenant_id)

        result = []
        # Use add_repo_to_name method for each record to add repo prefix to model_name
        for record in records:
            record["model_name"] = add_repo_to_name(
                model_repo=record["model_repo"],
                model_name=record["model_name"]
            )
            # Handle connect_status, use default value "Not Detected" if empty
            record["connect_status"] = ModelConnectStatusEnum.get_value(record.get("connect_status"))
            result.append(record)

        return ModelResponse(
            code=200,
            message="Successfully retrieved model list",
            data=result
        )
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to retrieve model list: {str(e)}",
            data=[]
        )


@router.post("/healthcheck", response_model=ModelResponse)
async def check_model_healthcheck(
        display_name: str = Query(..., description="Display name to check"),
        authorization: Optional[str] = Header(None)
):
    """
    Check and update model connectivity (health check), and return the latest status.
    Args:
        display_name: display_name of the model to check
    Returns:
        ModelResponse: contains connectivity and latest status
    """
    return await check_model_connectivity(display_name, authorization)


@router.post("/verify_config", response_model=ModelResponse)
async def verify_model_config(request: ModelRequest):
    """
    Verify the connectivity of the model configuration, do not save to database
    Args:
        request: model configuration information
    Returns:
        ModelResponse: contains connectivity test result
    """
    try:
        from services.model_health_service import verify_model_config_connectivity

        model_data = request.model_dump()

        # Call the verification service directly, do not split model_name
        result = await verify_model_config_connectivity(model_data)

        return result
    except Exception as e:
        return ModelResponse(
            code=500,
            message=f"Failed to verify model configuration: {str(e)}",
            data={
                "connectivity": False,
                "message": f"Verification failed: {str(e)}",
                "connect_status": ModelConnectStatusEnum.UNAVAILABLE.value
            }
        )

