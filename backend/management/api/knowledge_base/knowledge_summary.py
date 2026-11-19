# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from nexent.storage.errors import DeadlineExceeded, NotFound, ScopeDenied

from contracts.knowledge import ChangeSummaryRequest, VectorDatabaseType
from contracts.errors.exceptions import RuntimeServiceTimeoutError, TokenExpiredError
from permissions.models import CurrentUser
from permissions.resource_access import resource_read_tenant
from management.services.knowledge_base.summary_metadata import read_summary, update_summary
from infrastructure.agentos_identity import ServicePrincipal
from management.services.knowledge_base.summary_service import KnowledgeSummaryService
from management.services.permission.identity.session import get_current_user_id, get_current_user_info, authenticate
from management.services.configuration.tenant.settings import tenant_config_manager

router = APIRouter(prefix="/summary")
logger = logging.getLogger("knowledge_summary_app")


def _summary_response(summary):
    async def events():
        try:
            for char in summary:
                yield 'data: ' + json.dumps({'status': 'success', 'message': char}, ensure_ascii=False) + '\n\n'
                await asyncio.sleep(0.01)
            yield 'data: {"status": "completed"}\n\n'
        except Exception as error:  # noqa: BLE001 - Preserve the public SSE error boundary.
            yield 'data: ' + json.dumps({'status': 'error', 'message': str(error)}, ensure_ascii=False) + '\n\n'
    return StreamingResponse(events(), media_type='text/event-stream')


@router.post("/{index_name}/auto_summary")
async def auto_summary(
    http_request: Request,
    index_name: str = Path(..., description="Name of the index to get documents from"),
    batch_size: int = Query(1000, description="Number of documents to retrieve per batch"),
    model_id: Optional[int] = Query(None, description="Model ID to use for summary generation"),
    db_type: VectorDatabaseType = VectorDatabaseType.ELASTICSEARCH,
    tenant_id: str | None = None,
    authorization: Optional[str] = Header(None),
):
    """Summary Elasticsearch index_name by model"""
    try:
        user_id, tenant_id, language = get_current_user_info(authorization, http_request)
        if db_type != VectorDatabaseType.ELASTICSEARCH:
            raise NotImplementedError("DataMate SDK does not support raw search API.")
        service = KnowledgeSummaryService()

        # Get model_id from tenant config if not provided
        if model_id is None and tenant_id:
            try:
                tenant_config = tenant_config_manager.load_config(tenant_id)
                model_id_str = tenant_config.get("LLM_ID")
                if model_id_str:
                    model_id = int(model_id_str)
                    logger.info(f"Using LLM_ID {model_id} from tenant config for auto-summary")
                else:
                    logger.warning(f"No LLM_ID configured for tenant {tenant_id}, summary may be placeholder")
            except Exception as e:
                logger.warning(f"Failed to get LLM_ID from tenant config: {e}")

        summary = await service.generate(
            index_name=index_name,
            batch_size=batch_size,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
            model_id=model_id,
        )
        return _summary_response(summary)
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=401, detail=str(e))
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{index_name}' not found") from None
    except ScopeDenied:
        raise HTTPException(status_code=403, detail="No permission to modify this knowledge base") from None
    except Exception as e:
        if not isinstance(e, (DeadlineExceeded, RuntimeServiceTimeoutError)):
            logger.error(f"Knowledge base summary generation failed: {e}", exc_info=True)
        return StreamingResponse(
            iter(['data: {"status": "error", "message": "Knowledge base summary generation failed due to an internal error."}\n\n']),
            media_type="text/event-stream",
            status_code=500,
        )


@router.post("/{index_name}/summary")
async def change_summary(
    index_name: str = Path(..., description="Name of the index to get documents from"),
    change_summary_request: ChangeSummaryRequest = Body(None, description="knowledge base summary"),
    authorization: Optional[str] = Header(None),
):
    """Summary Elasticsearch index_name by user"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        summary_result = change_summary_request.summary_result
        return await update_summary(index_name, summary_result, ServicePrincipal(user_id, tenant_id))
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=401, detail=str(e))
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{index_name}' not found") from None
    except ScopeDenied:
        raise HTTPException(status_code=403, detail="No permission to modify this knowledge base") from None
    except DeadlineExceeded:
        raise HTTPException(status_code=500, detail="Knowledge base summary update failed: storage operation timed out") from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Knowledge base summary update failed: {str(e)}")


@router.get("/{index_name}/summary")
async def get_summary(
    index_name: str = Path(..., description="Name of the index to get documents from"),
    request: Request = None,
    current_user: CurrentUser = Depends(authenticate),
):
    """Get Elasticsearch index_name Summary"""
    try:
        target = resource_read_tenant(request, user=current_user)
        return await read_summary(index_name, ServicePrincipal(current_user.user_id, current_user.tenant_id), target_tenant=target)
    except HTTPException:
        raise
    except NotFound:
        if target:
            raise HTTPException(status_code=404, detail="Knowledge base not found") from None
        raise HTTPException(status_code=500, detail=(
            f"Failed to get knowledge base summary: Failed to get summary: Unable to get summary for index {index_name}"
        )) from None
    except ScopeDenied:
        raise HTTPException(status_code=403, detail="No permission to read this knowledge base") from None
    except DeadlineExceeded:
        raise HTTPException(status_code=500, detail="Failed to get knowledge base summary: storage operation timed out") from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get knowledge base summary: {str(e)}")
