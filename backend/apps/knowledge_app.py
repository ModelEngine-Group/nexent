from typing import Optional

from fastapi import HTTPException, Query, Body, Path, APIRouter, Header
from consts.model import ChangeSummaryRequest
from fastapi.responses import StreamingResponse
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from services.elasticsearch_service import ElasticSearchService, get_es
from utils.auth_utils import get_current_user_info, get_current_user_id
from consts.const import ES_API_KEY, ES_HOST
router = APIRouter(prefix="/summary")

@router.post("/{index_name}/auto_summary")
async def auto_summary(
            index_name: str = Path(..., description="Name of the index to get documents from"),
            batch_size: int = Query(1000, description="Number of documents to retrieve per batch"),
            authorization: Optional[str] = Header(None)
    ):
    """Summary Elasticsearch index_name by model"""
    try:
        user_id, tenant_id, language = get_current_user_info(authorization=authorization)
        es_core = ElasticSearchCore(
            host=ES_HOST,
            api_key=ES_API_KEY,
            embedding_model=None,
            verify_certs=False,
            ssl_show_warn=False,
        )
        es_core.embedding_model = get_es(tenant_id)
        service = ElasticSearchService()

        return await service.summary_index_name(
            index_name=index_name,
            batch_size=batch_size,
            es_core=es_core,
            user_id=user_id,
            tenant_id=tenant_id
        )
    except Exception as e:
        return StreamingResponse(
            f"data: {'status': 'error', 'message': '知识库摘要生成失败: '}\n\n",
            media_type="text/event-stream",
            status_code=500
        )


@router.post("/{index_name}/summary")
def change_summary(
            index_name: str = Path(..., description="Name of the index to get documents from"),
            change_summary_request: ChangeSummaryRequest = Body(None, description="knowledge base summary"),
            authorization: Optional[str] = Header(None)
    ):
    """Summary Elasticsearch index_name by user"""
    try:
        user_id = get_current_user_id(authorization)
        summary_result = change_summary_request.summary_result
        return ElasticSearchService().change_summary(index_name=index_name,summary_result=summary_result,user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"知识库摘要更新失败: {str(e)}")


@router.get("/{index_name}/summary")
def get_summary(
            index_name: str = Path(..., description="Name of the index to get documents from"),
    ):
    """Get Elasticsearch index_name Summary"""
    try:
        # Try to list indices as a health check
        return ElasticSearchService().get_summary(index_name=index_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取知识库摘要失败: {str(e)}")