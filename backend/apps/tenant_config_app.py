import logging
from http import HTTPStatus
from typing import List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import JSONResponse

from consts.const import DEPLOYMENT_VERSION, APP_VERSION
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
            status_code=HTTPStatus.OK,
            content={"deployment_version": DEPLOYMENT_VERSION,
                     "app_version": APP_VERSION,
                     "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to get deployment version, error: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get deployment version"
        )


@router.get("/load_knowledge_list")
def load_knowledge_list(
    authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        selected_knowledge_info = get_selected_knowledge_list(
            tenant_id=tenant_id, user_id=user_id)

        content = {"selectedKbNames": [item["index_name"] for item in selected_knowledge_info],
                   "selectedKbModels": [item["embedding_model_name"] for item in selected_knowledge_info],
                   "selectedKbSources": [item["knowledge_sources"] for item in selected_knowledge_info]}

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"content": content, "status": "success"}
        )
    except Exception as e:
        logger.error(f"load knowledge list failed, error: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to load configuration"
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
                status_code=HTTPStatus.OK,
                content={"message": "update success", "status": "success"}
            )
        else:
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail="Failed to update configuration"
            )
    except Exception as e:
        logger.error(f"update knowledge list failed, error: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration"
        )
