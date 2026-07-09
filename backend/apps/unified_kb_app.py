"""
Unified KB API — Single entry point for both local and external knowledge bases.

Route prefix: /api/v1/kb
All KB operations (whether local ES or external Dify/AIDP) go through this unified interface.
The dispatcher (ExternalKnowledgeBaseService) routes to the appropriate adapter based on adapter_id.

Key design decisions:
- All endpoints accept adapter_id in path (local KB also has its own adapter_id)
- No if/else branching based on platform — unified through dispatcher
- Supports aggregated queries across multiple adapters (retrieve_all, list_all)

Migration strategy:
- Old routes (/indices, /nb/v1/knowledge, /dify, /aidp, /datamate) remain functional
- They receive Deprecation headers via DeprecatedRoutesMiddleware
- New code should use /api/v1/kb/* exclusively
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Path, Query, UploadFile, status
from pydantic import BaseModel, Field

from database.external_kb_adapter_db import get_adapter_by_id
from services.external_kb_service import ExternalKnowledgeBaseService

logger = logging.getLogger("unified_kb_app")

router = APIRouter(prefix="/api/v1/kb", tags=["unified-kb"])


# =============================================================================
# Auth helper (injected via Depends)
# =============================================================================

def _get_current_user(authorization: Optional[str] = Header(None)) -> tuple:
    """Extract (user_id, tenant_id) from authorization header."""
    from apps.middleware.authorize_middleware import get_current_user_id
    return get_current_user_id(authorization)


# =============================================================================
# Request/Response models
# =============================================================================

class RegisterAdapterRequest(BaseModel):
    platform: str
    name: Optional[str] = None
    external_kb_config: Optional[Dict[str, Any]] = None
    enabled: bool = True
    status: str = "running"


class UpdateAdapterRequest(BaseModel):
    name: Optional[str] = None
    external_kb_config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    status: Optional[str] = None


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    embedding_model_config: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = {}


class UpdateKnowledgeBaseRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


# ============================================================================
# Standard Request Models
# ============================================================================
class RetrievalModel(BaseModel):
    """标准检索模型配置"""
    search_method: str = Field("keyword", alias="search_method", description="检索方法：keyword/semantic/hybrid")
    top_k: int = Field(5, alias="top_k", ge=1, le=100)
    score_threshold: float = Field(0.0, alias="score_threshold", ge=0.0, le=1.0)
    reranking_enable: bool = Field(False, alias="reranking_enable")
    multimodal_enable: bool = Field(False, alias="multimodal_enable", description="是否启用多模态检索")

    class Config:
        populate_by_name = True


class RetrieveRequest(BaseModel):
    """标准请求模型（向后兼容：同时支持 kb_ids 和 knowledge_base_ids）"""
    query: str
    # 标准字段名
    knowledge_base_ids: Optional[List[str]] = Field(None, alias="knowledge_base_ids")
    # 向后兼容：旧字段名
    kb_ids: Optional[List[str]] = Field(None, alias="kb_ids")
    # 检索模型配置
    retrieval_model: Optional[RetrievalModel] = Field(None, alias="retrieval_model")
    # 向后兼容：旧字段名（当 retrieval_model 不存在时使用）
    top_k: Optional[int] = Field(None, alias="top_k")
    search_mode: Optional[str] = Field(None, alias="search_mode")
    score_threshold: Optional[float] = Field(None, alias="score_threshold")
    rerank: Optional[bool] = Field(None, alias="rerank")

    class Config:
        populate_by_name = True

    def get_knowledge_base_ids(self) -> List[str]:
        """获取知识库 ID 列表（优先使用标准字段名，向后兼容 kb_ids）"""
        return self.knowledge_base_ids or self.kb_ids or []

    def get_search_method(self) -> str:
        """获取检索方法（优先使用 retrieval_model，向后兼容 search_mode）"""
        if self.retrieval_model:
            return self.retrieval_model.search_method
        return self.search_mode or "keyword"  # 默认值

    def get_top_k(self) -> int:
        """获取 top_k（优先使用 retrieval_model，向后兼容）"""
        if self.retrieval_model:
            return self.retrieval_model.top_k
        return self.top_k or 5

    def get_score_threshold(self) -> float:
        """获取 score_threshold（优先使用 retrieval_model，向后兼容）"""
        if self.retrieval_model:
            return self.retrieval_model.score_threshold
        return self.score_threshold or 0.0

    def is_reranking_enable(self) -> bool:
        """是否启用重排序（优先使用 retrieval_model，向后兼容 rerank）"""
        if self.retrieval_model:
            return self.retrieval_model.reranking_enable
        return self.rerank or False

    def is_multimodal_enable(self) -> bool:
        """是否启用多模态检索"""
        if self.retrieval_model:
            return self.retrieval_model.multimodal_enable
        return False


class RetrieveAllRequest(BaseModel):
    """跨适配器联合检索请求"""
    query: str
    kb_refs: List[Dict[str, Any]]  # [{"adapter_id": int, "kb_id": str}, ...]
    top_k: int = 5
    search_mode: str = "hybrid"
    score_threshold: float = 0.0
    rerank: bool = False


# =============================================================================
# Adapter management endpoints
# =============================================================================

@router.get("/adapters", summary="List all adapters for current tenant")
def list_adapters(
    enabled_only: bool = Query(False),
    auth: tuple = Depends(_get_current_user),
):
    """List all registered adapters. Auto-provisions local adapter if missing."""
    _, tenant_id = auth
    # Ensure local adapter exists so it always appears in list
    ExternalKnowledgeBaseService.ensure_local_adapter(tenant_id)
    return ExternalKnowledgeBaseService.list_adapters(tenant_id, enabled_only)


@router.post("/adapters", status_code=status.HTTP_201_CREATED, summary="Register new adapter")
def register_adapter(
    request: RegisterAdapterRequest,
    auth: tuple = Depends(_get_current_user),
):
    """Register a new external KB adapter (e.g. dify, aidp)."""
    user_id, tenant_id = auth
    return ExternalKnowledgeBaseService.register_adapter(
        request_data={
            "platform": request.platform,
            "name": request.name,
            "external_kb_config": request.external_kb_config,
            "enabled": request.enabled,
            "status": request.status,
            "user_id": user_id,
        },
        tenant_id=tenant_id,
    )


@router.get("/adapters/{adapter_id}", summary="Get adapter details")
def get_adapter(
    adapter_id: int = Path(..., description="Adapter ID"),
    auth: tuple = Depends(_get_current_user),
):
    _, tenant_id = auth
    adapter = get_adapter_by_id(adapter_id, tenant_id)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Adapter {adapter_id} not found")
    return adapter


@router.put("/adapters/{adapter_id}", summary="Update adapter config")
def update_adapter(
    request: UpdateAdapterRequest,
    adapter_id: int = Path(..., description="Adapter ID"),
    auth: tuple = Depends(_get_current_user),
):
    _, tenant_id = auth
    updates = request.dict(exclude_none=True)
    result = ExternalKnowledgeBaseService.update_adapter(adapter_id, tenant_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Adapter {adapter_id} not found")
    return result


@router.delete("/adapters/{adapter_id}", summary="Delete adapter (soft)")
def delete_adapter(
    adapter_id: int = Path(..., description="Adapter ID"),
    auth: tuple = Depends(_get_current_user),
):
    _, tenant_id = auth
    success = ExternalKnowledgeBaseService.delete_adapter(adapter_id, tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Adapter {adapter_id} not found")
    return {"success": True}


@router.get("/adapters/{adapter_id}/health", summary="Check adapter health")
def check_health(
    adapter_id: int = Path(..., description="Adapter ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Call adapter's health_check and update DB health_status."""
    _, tenant_id = auth
    return ExternalKnowledgeBaseService.check_health(adapter_id, tenant_id)


@router.get("/adapters/{adapter_id}/capabilities", summary="Get adapter capabilities")
def get_capabilities(
    adapter_id: int = Path(..., description="Adapter ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Pull capabilities from adapter and persist to DB."""
    _, tenant_id = auth
    return ExternalKnowledgeBaseService.refresh_capabilities(adapter_id, tenant_id)


# =============================================================================
# Knowledge base CRUD operations
# =============================================================================

@router.get("/adapters/{adapter_id}/knowledge-bases", summary="List knowledge bases")
def list_knowledge_bases(
    adapter_id: int = Path(..., description="Adapter ID"),
    keyword: Optional[str] = Query(None, description="Filter by keyword"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth: tuple = Depends(_get_current_user),
):
    """List knowledge bases for the specified adapter."""
    _, tenant_id = auth
    adapter = ExternalKnowledgeBaseService.get_adapter(adapter_id, tenant_id)
    try:
        kbs = adapter.list_knowledge_bases(keyword=keyword, page=page, page_size=page_size)
        return {
            "list": [kb.__dict__ for kb in kbs],
            "total": len(kbs),
            "page": page,
            "page_size": page_size,
            "has_more": len(kbs) == page_size,
        }
    finally:
        adapter.close()


@router.post("/adapters/{adapter_id}/knowledge-bases", status_code=status.HTTP_201_CREATED,
             summary="Create knowledge base")
def create_knowledge_base(
    request: CreateKnowledgeBaseRequest,
    adapter_id: int = Path(..., description="Adapter ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Create a new knowledge base via adapter."""
    user_id, tenant_id = auth
    return ExternalKnowledgeBaseService.create_knowledge_base(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name=request.name,
        description=request.description or "",
        embedding_model_config=request.embedding_model_config,
        **(request.extra or {}),
    )


@router.get("/adapters/{adapter_id}/knowledge-bases/{kb_id}", summary="Get knowledge base details")
def get_knowledge_base(
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    auth: tuple = Depends(_get_current_user),
):
    _, tenant_id = auth
    return ExternalKnowledgeBaseService.get_knowledge_base(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id="",  # not used by adapter
        kb_id=kb_id,
    )


@router.put("/adapters/{adapter_id}/knowledge-bases/{kb_id}", summary="Update knowledge base")
def update_knowledge_base(
    request: UpdateKnowledgeBaseRequest,
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Update knowledge base metadata (name, description)."""
    user_id, tenant_id = auth
    body = request.dict(exclude_none=True)
    return ExternalKnowledgeBaseService.update_knowledge_base(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id=user_id,
        kb_id=kb_id,
        body=body,
    )


@router.delete("/adapters/{adapter_id}/knowledge-bases/{kb_id}", summary="Delete knowledge base")
def delete_knowledge_base(
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Delete a knowledge base and all its documents."""
    user_id, tenant_id = auth
    success = ExternalKnowledgeBaseService.delete_knowledge_base(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id=user_id,
        kb_id=kb_id,
    )
    return {"success": success}


# =============================================================================
# Document operations
# =============================================================================

@router.get("/adapters/{adapter_id}/knowledge-bases/{kb_id}/documents",
            summary="List documents in knowledge base")
def list_documents(
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth: tuple = Depends(_get_current_user),
):
    _, tenant_id = auth
    return ExternalKnowledgeBaseService.list_documents(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id="",
        kb_id=kb_id,
        page=page,
        page_size=page_size,
    )


@router.post("/adapters/{adapter_id}/knowledge-bases/{kb_id}/documents",
             status_code=status.HTTP_201_CREATED, summary="Upload documents",
             description="Upload files via multipart/form-data (standard). The service layer streams files to the adapter.")
def upload_documents(
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    files: List[UploadFile] = File(..., description="Files to upload"),
    chunking_strategy: str = Form("basic", description="Chunking strategy: basic / table / hierarchical"),
    metadata: Optional[str] = Form(None, description="Optional JSON metadata as string"),
    auth: tuple = Depends(_get_current_user),
):
    """Upload documents using standard multipart/form-data."""
    user_id, tenant_id = auth
    return ExternalKnowledgeBaseService.upload_documents(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id=user_id,
        kb_id=kb_id,
        files=files,
        chunking_strategy=chunking_strategy,
        metadata_str=metadata,
    )


@router.delete("/adapters/{adapter_id}/knowledge-bases/{kb_id}/documents/{doc_id}",
               summary="Delete document")
def delete_document(
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    doc_id: str = Path(..., description="Document ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Delete a document from knowledge base."""
    user_id, tenant_id = auth
    success = ExternalKnowledgeBaseService.delete_document(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id=user_id,
        kb_id=kb_id,
        doc_id=doc_id,
    )
    return {"success": success}


@router.get("/adapters/{adapter_id}/knowledge-bases/{kb_id}/documents/{doc_id}/status",
            summary="Get document processing status")
def get_document_status(
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    doc_id: str = Path(..., description="Document ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Check indexing status and error messages for a document."""
    _, tenant_id = auth
    return ExternalKnowledgeBaseService.get_document_status(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id="",
        kb_id=kb_id,
        doc_id=doc_id,
    )


@router.get("/adapters/{adapter_id}/knowledge-bases/{kb_id}/documents/{doc_id}/download-url",
            summary="Get document download URL")
def get_document_download_url(
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    doc_id: str = Path(..., description="Document ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Generate a signed download URL for the document."""
    _, tenant_id = auth
    return ExternalKnowledgeBaseService.get_document_download_url(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
        user_id="",
        kb_id=kb_id,
        doc_id=doc_id,
    )


# =============================================================================
# Search operations
# =============================================================================

@router.post("/adapters/{adapter_id}/knowledge-bases/{kb_id}/retrieve",
             summary="Retrieve from single KB",
             description="Execute semantic/hybrid/keyword search on a single knowledge base.")
def retrieve(
    request: RetrieveRequest,
    adapter_id: int = Path(..., description="Adapter ID"),
    kb_id: str = Path(..., description="Knowledge base ID"),
    auth: tuple = Depends(_get_current_user),
):
    """Execute semantic/hybrid/keyword search on a single knowledge base."""
    _, tenant_id = auth

    # Log usage of deprecated request fields
    if request.kb_ids is not None:
        logger.warning(
            "Deprecated field 'kb_ids' used in retrieve request — use 'knowledge_base_ids' instead",
        )
    if request.top_k is not None or request.search_mode is not None or request.rerank is not None:
        logger.warning(
            "Deprecated flat retrieve fields used (top_k/search_mode/rerank) — use 'retrieval_model' instead",
        )

    # Convert to dict format expected by service
    req_dict = request.model_dump()
    req_dict["kb_ids"] = [kb_id]  # Override with path param
    # Service returns V4 structure via SearchResponse.to_dict() directly
    return ExternalKnowledgeBaseService.retrieve(adapter_id, tenant_id, req_dict)


@router.post("/retrieve-all", summary="Retrieve across multiple KBs (may span adapters)")
def retrieve_all(
    request: RetrieveAllRequest,
    auth: tuple = Depends(_get_current_user),
):
    """
    Execute search across multiple knowledge bases, potentially from different adapters.

    kb_refs format: [{"adapter_id": 1, "kb_id": "abc"}, {"adapter_id": 2, "kb_id": "xyz"}]
    Results are merged and re-ranked globally by score.
    """
    _, tenant_id = auth
    from nexent.core.knowledge_base.platform_adapters import SearchRequest

    # Group by adapter
    adapter_groups: Dict[int, List[str]] = {}
    for ref in request.kb_refs:
        aid = ref["adapter_id"]
        kb_id = ref["kb_id"]
        adapter_groups.setdefault(aid, []).append(kb_id)

    # Execute search per adapter
    all_results = []
    for adapter_id, kb_ids in adapter_groups.items():
        req = SearchRequest(
            query=request.query,
            kb_ids=kb_ids,
            top_k=request.top_k,
            search_mode=request.search_mode,
            score_threshold=request.score_threshold,
            rerank=request.rerank,
        )
        try:
            response = ExternalKnowledgeBaseService.retrieve(adapter_id, tenant_id, req)
            all_results.extend(response.get("records", []))
        except Exception as exc:
            logger.warning("Adapter %s search failed: %s", adapter_id, exc)

    # Global re-rank by score
    all_results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    # Take top_k from merged results
    top_records = all_results[:request.top_k]

    # Return V4 nested structure: {records: [{segment, score}], query}
    return {
        "records": top_records,
        "query": request.query,
    }


# =============================================================================
# Aggregated list endpoint
# =============================================================================

@router.get("/knowledge-bases/all", summary="List all KBs across all adapters")
def list_all_knowledge_bases(
    keyword: Optional[str] = Query(None, description="Filter by keyword"),
    auth: tuple = Depends(_get_current_user),
):
    """
    Aggregate knowledge bases from all enabled adapters for the current tenant.
    Useful for UI dropdowns that need to show both local and external KBs.
    """
    user_id, tenant_id = auth
    # Ensure local adapter exists
    ExternalKnowledgeBaseService.ensure_local_adapter(tenant_id, user_id)
    # Aggregate from all adapters
    all_kbs = ExternalKnowledgeBaseService.list_all_external_knowledge_bases(
        tenant_id=tenant_id,
        keyword=keyword,
    )
    return {
        "list": all_kbs,
        "total": len(all_kbs),
        "page": 1,
        "page_size": len(all_kbs),
        "has_more": False,
    }
