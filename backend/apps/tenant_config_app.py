import logging
from typing import List, Optional

import requests
from fastapi import APIRouter, Body, Header
from fastapi.responses import JSONResponse

from consts.const import DEPLOYMENT_VERSION, ELASTICSEARCH_SERVICE
from services.tenant_config_service import get_selected_knowledge_list, update_selected_knowledge
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("tenant_config_app")
router = APIRouter(prefix="/tenant_config")


@router.get("/deployment_version")
def get_deployment_version():
    """
    Get current deployment version (speed or full)
    """
    try:
        return JSONResponse(
            status_code=200,
            content={"deployment_version": DEPLOYMENT_VERSION,
                     "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to get deployment version, error: {e}")
        return JSONResponse(
            status_code=500,
            content={"message": "Failed to get deployment version",
                     "status": "error"}
        )


@router.get("/load_knowledge_list")
def load_knowledge_list(
    authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        selected_knowledge_info = get_selected_knowledge_list(
            tenant_id=tenant_id, user_id=user_id)

        kb_name_list = [item["index_name"] for item in selected_knowledge_info]

        # Query embedding models from Elasticsearch service
        embedding_models = []
        if kb_name_list:
            try:
                api_url = f"{ELASTICSEARCH_SERVICE}/indices?include_stats=true"
                response = requests.get(api_url, timeout=10)
                response.raise_for_status()

                index_to_model = {}
                for index_info in response.json().get("indices_info", []):
                    index_name = index_info.get("name")
                    embedding_model = index_info.get("stats", {}).get(
                        "base_info", {}).get("embedding_model", "")
                    if index_name:
                        index_to_model[index_name] = embedding_model

                embedding_models = [index_to_model.get(
                    kb_name, "") for kb_name in kb_name_list]

            except Exception as e:
                logger.error(f"API call failed: {e}")
                embedding_models = []

        content = {"selectedKbNames": kb_name_list,
                   "selectedKbModels": embedding_models,
                   "selectedKbSources": [item["knowledge_sources"] for item in selected_knowledge_info]}

        return JSONResponse(
            status_code=200,
            content={"content": content, "status": "success"}
        )
    except Exception as e:
        logger.error(f"load knowledge list failed, error: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to load configuration", "status": "error"}
        )


@router.post("/update_knowledge_list")
def update_knowledge_list(
    authorization: Optional[str] = Header(None),
    knowledge_list: List[str] = Body(None)
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = update_selected_knowledge(
            tenant_id=tenant_id, user_id=user_id, index_name_list=knowledge_list)
        if result:
            return JSONResponse(
                status_code=200,
                content={"message": "update success", "status": "success"}
            )
        else:
            return JSONResponse(
                status_code=400,
                content={"message": "update failed", "status": "error"}
            )
    except Exception as e:
        logger.error(f"update knowledge list failed, error: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to update configuration",
                     "status": "error"}
        )
