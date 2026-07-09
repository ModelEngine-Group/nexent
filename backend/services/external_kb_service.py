"""
ExternalKnowledgeBaseService — backend orchestration layer for external KB adapters.

Bridges DB records (external_kb_adapter_t) with adapter instances from the
ExternalKBAdapterRegistry. Each platform maps to a concrete adapter class
(e.g. LocalKBAdapter for "local", future adapters for external platforms).

This module is the single authoritative place where:
  - adapter DB records are translated into live in-process adapter instances
  - KB lists from multiple adapters are aggregated
  - adapter health / capabilities are refreshed and persisted
"""

import logging
from typing import Any, Dict, List, Optional

from nexent.core.knowledge_base.platform_adapters import (
    ExternalKBAdapter,
    ExternalKBAdapterRegistry,
    SearchRequest,
)

logger = logging.getLogger("external_kb_service")


def _build_adapter(adapter_record: Dict[str, Any], user_id: str = "") -> ExternalKBAdapter:
    """Build a live adapter instance from a DB record dict."""
    platform = adapter_record.get("platform", "").lower()
    config = adapter_record.get("external_kb_config") or {}
    # Always carry tenant_id + user_id so LocalKBAdapter can scope ES/PG operations
    if isinstance(config, dict):
        config = {
            **config,
            "tenant_id": adapter_record.get("tenant_id", ""),
            "user_id": user_id or adapter_record.get("user_id", ""),
        }
    return ExternalKBAdapterRegistry.instantiate(platform, config)


class ExternalKnowledgeBaseService:
    """
    Orchestration layer for external KB adapters.
    All methods are static; there is no per-request state.
    """

    # ------------------------------------------------------------------
    # Adapter factory
    # ------------------------------------------------------------------

    @staticmethod
    def get_adapter(adapter_id: int, tenant_id: str) -> ExternalKBAdapter:
        """
        Return a live adapter instance for the specified adapter record.

        Raises ValueError if the adapter is not found or disabled.
        """
        from database.external_kb_adapter_db import get_adapter_by_id

        adapter = get_adapter_by_id(adapter_id, tenant_id)
        if not adapter:
            raise ValueError(f"Adapter {adapter_id} not found for tenant {tenant_id}")
        if not adapter.get("enabled"):
            raise ValueError(f"Adapter {adapter_id} is disabled")
        return _build_adapter(adapter)

    # ------------------------------------------------------------------
    # KB list aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def list_all_external_knowledge_bases(
        tenant_id: str, keyword: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Aggregate KB lists from all enabled adapters for a tenant.

        Adapters that fail are skipped with a warning (graceful degradation).
        """
        from database.external_kb_adapter_db import query_adapters_by_tenant

        adapters = query_adapters_by_tenant(tenant_id, enabled_only=True)
        all_external_kbs: List[Dict[str, Any]] = []

        for adapter in adapters:
            try:
                adapter_obj = _build_adapter(adapter)
                kbs = adapter_obj.list_knowledge_bases(keyword=keyword, page_size=200)
                for kb in kbs:
                    kb_dict = kb.to_dict()
                    kb_dict.update({
                        "adapter_id": adapter["adapter_id"],
                        "adapter_name": adapter["name"],
                        "platform": adapter["platform"],
                        "source": "external",
                    })
                    all_external_kbs.append(kb_dict)
                adapter_obj.close()
            except Exception as exc:
                logger.warning(
                    "Failed to list KBs from adapter %s (%s): %s",
                    adapter.get("name"),
                    adapter.get("adapter_id"),
                    exc,
                )

        return all_external_kbs

    # ------------------------------------------------------------------
    # Search / retrieve
    # ------------------------------------------------------------------

    @staticmethod
    def retrieve(adapter_id: int, tenant_id: str, request) -> Dict[str, Any]:
        """
        Execute a retrieve call via the specified adapter.

        ``request`` should be a dict matching POST /api/v1/retrieve body, or a
        SearchRequest dataclass.
        """
        adapter = ExternalKnowledgeBaseService.get_adapter(adapter_id, tenant_id)

        if isinstance(request, dict):
            kb_ids = request.get("kb_ids") or request.get("knowledge_base_ids", [])
            retrieval_model = request.get("retrieval_model") or {}
            req = SearchRequest(
                query=request["query"],
                kb_ids=kb_ids,
                top_k=retrieval_model.get("top_k", request.get("top_k", 5)),
                search_mode=retrieval_model.get("search_method", request.get("search_mode", "hybrid")),
                score_threshold=retrieval_model.get("score_threshold", request.get("score_threshold", 0.0)),
                rerank=retrieval_model.get("reranking_enable", request.get("rerank", False)),
            )
        else:
            req = request

        try:
            response = adapter.search(req)
            # Return V4 nested structure: {records: [{segment, score}], query}
            return response.to_dict()
        finally:
            adapter.close()

    # ------------------------------------------------------------------
    # Capabilities & health
    # ------------------------------------------------------------------

    @staticmethod
    def refresh_capabilities(adapter_id: int, tenant_id: str) -> Dict[str, Any]:
        """Pull capabilities from the adapter and persist them to DB."""
        from database.external_kb_adapter_db import update_adapter

        adapter = ExternalKnowledgeBaseService.get_adapter(adapter_id, tenant_id)
        try:
            caps = adapter.get_capabilities()
            update_adapter(adapter_id, tenant_id, {"capabilities": caps.to_dict()})
            return caps.to_dict()
        finally:
            adapter.close()

    @staticmethod
    def check_health(adapter_id: int, tenant_id: str) -> Dict[str, Any]:
        """Call the adapter's health_check and update DB health_status."""
        from database.external_kb_adapter_db import update_adapter_status

        adapter = ExternalKnowledgeBaseService.get_adapter(adapter_id, tenant_id)
        try:
            health = adapter.health_check()
            status = "ok" if health.get("status") == "ok" else "error"
            update_adapter_status(adapter_id, tenant_id, "running", health_status=status)
            return health
        finally:
            adapter.close()

    # ------------------------------------------------------------------
    # Registration helper (used by the HTTP router)
    # ------------------------------------------------------------------

    @staticmethod
    def register_adapter(request_data: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        """Create a new adapter DB record.

        ``platform="local"`` is rejected: the local adapter is always
        auto-provisioned by ``ensure_local_adapter`` and must not be
        manually registered.
        """
        from database.external_kb_adapter_db import create_adapter

        platform = request_data["platform"].lower()

        # Local adapter is auto-provisioned; manual registration would create
        # duplicate records and break the dispatcher's single-local assumption.
        if platform == "local":
            raise ValueError(
                "The local adapter is auto-provisioned and cannot be manually registered. "
                "Access it through the adapter list endpoint."
            )

        # Validate that an adapter is registered for this platform
        if ExternalKBAdapterRegistry.get(platform) is None:
            raise ValueError(
                f"No adapter registered for platform '{platform}'. "
                f"Registered: {ExternalKBAdapterRegistry.registered_platforms()}"
            )

        record = create_adapter(
            {
                "platform": platform,
                "name": request_data.get("name", platform),
                "external_kb_config": request_data.get("external_kb_config"),
                "tenant_id": tenant_id,
                "enabled": request_data.get("enabled", True),
                "status": request_data.get("status", "running"),
                "user_id": request_data.get("user_id"),
            }
        )
        return record

    @staticmethod
    def update_adapter(adapter_id: int, tenant_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update adapter metadata in DB."""
        from database.external_kb_adapter_db import update_adapter as _update_adapter
        return _update_adapter(adapter_id, tenant_id, updates)

    @staticmethod
    def delete_adapter(adapter_id: int, tenant_id: str) -> bool:
        """Soft-delete the adapter record.

        The built-in local adapter cannot be deleted.
        """
        from database.external_kb_adapter_db import get_adapter_by_id, delete_adapter
        record = get_adapter_by_id(adapter_id, tenant_id)
        if not record:
            return False
        if record.get("platform") == "local":
            raise ValueError("Cannot delete the built-in local adapter")
        return delete_adapter(adapter_id, tenant_id)

    # ------------------------------------------------------------------
    # Adapter management helpers (simplified — no container lifecycle)
    # ------------------------------------------------------------------

    @staticmethod
    def ensure_local_adapter(tenant_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ensure a 'local' adapter record exists for the tenant.

        Idempotent via a single ``upsert_adapter_by_platform`` DB roundtrip:
        resolves any race where two concurrent requests try to auto-provision
        the same tenant. Returns the adapter record.

        Used by unified_kb_app.py to auto-provision local adapter so users
        can immediately access local KBs via the unified API without manual
        registration.
        """
        from database.external_kb_adapter_db import upsert_adapter_by_platform

        # Resolve current capabilities if the platform adapter class is loaded.
        caps = {}
        try:
            local_cls = ExternalKBAdapterRegistry.get("local")
            if local_cls is not None:
                caps = local_cls({}).get_capabilities().to_dict()
        except Exception as exc:
            logger.debug("Skipping capability cache for local adapter: %s", exc)

        record = upsert_adapter_by_platform(
            tenant_id=tenant_id,
            platform="local",
            data={
                "name": "本地知识库",
                "external_kb_config": {},
                "enabled": True,
                "status": "running",
                "health_status": "unknown",
                "capabilities": caps,
                "user_id": user_id,
            },
        )
        logger.info(
            "Local adapter present for tenant %s (adapter_id=%s)",
            tenant_id,
            record["adapter_id"],
        )
        return record

    @staticmethod
    def list_adapters(tenant_id: str, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """List all adapters for a tenant."""
        from database.external_kb_adapter_db import query_adapters_by_tenant
        return query_adapters_by_tenant(tenant_id, enabled_only=enabled_only)

    @staticmethod
    def get_adapter_detail(adapter_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a single adapter record by ID."""
        from database.external_kb_adapter_db import get_adapter_by_id
        return get_adapter_by_id(adapter_id, tenant_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def resolve(adapter_id: int, tenant_id: str, user_id: str = ""):
        """Return (adapter_record, live_adapter_instance)."""
        from database.external_kb_adapter_db import get_adapter_by_id
        adapter_record = get_adapter_by_id(adapter_id, tenant_id)
        if not adapter_record:
            raise ValueError(f"Adapter {adapter_id} not found for tenant {tenant_id}")
        if not adapter_record.get("enabled"):
            raise ValueError(f"Adapter {adapter_id} is disabled")
        impl = _build_adapter(adapter_record, user_id=user_id)
        return adapter_record, impl

    # ------------------------------------------------------------------
    # External KB CRUD operations (delegated to adapter)
    # ------------------------------------------------------------------

    @staticmethod
    def create_knowledge_base(
        adapter_id: int, tenant_id: str, user_id: str,
        name: str, description: str = "",
        embedding_model_config: Optional[dict] = None, **extra
    ) -> dict:
        """Create a knowledge base via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.create_knowledge_base:
            raise NotImplementedError(
                f"Adapter '{record['name']}' ({record['platform']}) does not support creating KBs"
            )
        try:
            result = impl.create_knowledge_base(
                name=name,
                description=description,
                embedding_model=embedding_model_config.get("model_name", "") if embedding_model_config else "",
                metadata=embedding_model_config,
                **extra
            )
            return result.to_dict() if hasattr(result, 'to_dict') else result
        finally:
            impl.close()

    @staticmethod
    def get_knowledge_base(adapter_id: int, tenant_id: str, user_id: str, kb_id: str) -> dict:
        """Get knowledge base details via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        try:
            result = impl.get_knowledge_base(kb_id)
            return result.to_dict() if hasattr(result, 'to_dict') else result
        finally:
            impl.close()

    @staticmethod
    def update_knowledge_base(
        adapter_id: int, tenant_id: str, user_id: str, kb_id: str, body: dict
    ) -> dict:
        """Update knowledge base via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.update_knowledge_base:
            raise NotImplementedError(
                f"Adapter '{record['name']}' does not support updating KBs"
            )
        try:
            result = impl.update_knowledge_base(
                kb_id=kb_id,
                name=body.get("name", ""),
                description=body.get("description", ""),
            )
            return result.to_dict() if hasattr(result, 'to_dict') else result
        finally:
            impl.close()

    @staticmethod
    def delete_knowledge_base(adapter_id: int, tenant_id: str, user_id: str, kb_id: str) -> bool:
        """Delete knowledge base via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.delete_knowledge_base:
            raise NotImplementedError(
                f"Adapter '{record['name']}' does not support deleting KBs"
            )
        try:
            return impl.delete_knowledge_base(kb_id)
        finally:
            impl.close()

    @staticmethod
    def list_documents(
        adapter_id: int, tenant_id: str, user_id: str,
        kb_id: str, page: int = 1, page_size: int = 50
    ) -> dict:
        """List documents via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.list_documents:
            raise NotImplementedError(
                f"Adapter '{record['name']}' does not support listing documents"
            )
        try:
            return impl.list_documents(kb_id, page, page_size)
        finally:
            impl.close()

    @staticmethod
    def upload_documents(
        adapter_id: int, tenant_id: str, user_id: str,
        kb_id: str, files: List["UploadFile"],
        chunking_strategy: str = "basic",
        metadata_str: Optional[str] = None,
    ) -> dict:
        """Upload documents to a knowledge base via the appropriate adapter.

        Streams files from List[UploadFile] to the adapter. The adapter handles
        the actual storage (MinIO/s3/local) and data-process triggering.
        The adapter must accept ``chunking_strategy`` as a kwarg and use it (no hardcoding).
        """
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.upload_document:
            raise NotImplementedError(
                f"Adapter '{record['name']}' ({record['platform']}) does not support uploading documents"
            )
        try:
            return impl.upload_documents(
                kb_id=kb_id,
                upload_files=files,
                chunking_strategy=chunking_strategy,
            )
        finally:
            impl.close()

    @staticmethod
    def delete_document(
        adapter_id: int, tenant_id: str, user_id: str, kb_id: str, doc_id: str
    ) -> bool:
        """Delete document via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.delete_document:
            raise NotImplementedError(
                f"Adapter '{record['name']}' does not support deleting documents"
            )
        try:
            return impl.delete_document(kb_id, doc_id)
        finally:
            impl.close()

    @staticmethod
    def get_document_status(
        adapter_id: int, tenant_id: str, user_id: str, kb_id: str, doc_id: str
    ) -> dict:
        """Get document status via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.query_document_status:
            raise NotImplementedError(
                f"Adapter '{record['name']}' does not support document status"
            )
        try:
            return impl.get_document_status(kb_id, doc_id)
        finally:
            impl.close()

    @staticmethod
    def get_document_download_url(
        adapter_id: int, tenant_id: str, user_id: str, kb_id: str, doc_id: str
    ) -> dict:
        """Get document download URL via adapter."""
        record, impl = ExternalKnowledgeBaseService.resolve(adapter_id, tenant_id, user_id=user_id)
        if not impl.capabilities.download_document:
            raise NotImplementedError(
                f"Adapter '{record['name']}' does not support document download"
            )
        try:
            return impl.get_document_download_url(kb_id, doc_id)
        finally:
            impl.close()
