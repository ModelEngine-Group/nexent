"""iData route set (mounted at /idata).

Contract mirrored from:
  - backend/services/idata_service.py — knowledgeSpaces/query and
    knowledgeBases/query: POST + Bearer, response envelope
    ``{"code": "1", "msg": ..., "data": [...], "msgParams": null}``;
    a code other than the string "1" is an error.
  - sdk/nexent/core/tools/idata_search_tool.py — retrievals: POST with
    ``{userId, knowledgeBaseFilter, question, rankTopN, ...}``, response
    ``{"code": "1", "data": {"retrievalData": [{"chunks": [...]}]}}`` where
    each chunk carries ``{documentId, documentName, content, datasetId,
    createTime(ms), reRankScore, vsScore, esScore, title}``; download URLs
    are built client-side as ``.../documents/download?userId=...&knowledgeBaseId=...&documentId=...``.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

from mock_common import StateStore, require_bearer, term_boost

_IDATA_PATH = "/apiaccess/modelmate/north/machine/v1"


def _envelope(data: Any) -> Dict[str, Any]:
    return {"code": "1", "msg": "success", "data": data, "msgParams": None}


def create_router(state: StateStore) -> APIRouter:
    router = APIRouter(prefix="/idata")

    @router.post(f"{_IDATA_PATH}/knowledgeSpaces/query")
    def query_knowledge_spaces(
        body: Dict[str, Any] = Body(...),
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_bearer(authorization)
        spaces: List[Dict[str, Any]] = state.data.get("spaces", [])
        return _envelope(spaces)

    @router.post(f"{_IDATA_PATH}/knowledgeBases/query")
    def query_knowledge_bases(
        body: Dict[str, Any] = Body(...),
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_bearer(authorization)
        space_id = str(body.get("knowledgeSpaceId") or "")
        kbs_by_space: Dict[str, List[Dict[str, Any]]] = state.data.get("kbs_by_space", {})
        if space_id not in kbs_by_space:
            # Unknown space returns an empty list, not an error — the real
            # service behaves the same way for spaces without KBs.
            return _envelope([])
        return _envelope(kbs_by_space[space_id])

    @router.post(f"{_IDATA_PATH}/retrievals")
    def retrievals(
        body: Dict[str, Any] = Body(...),
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        require_bearer(authorization)
        question = str(body.get("question") or "")
        rank_top_n = int(body.get("rankTopN") or 5)
        kb_filter = body.get("knowledgeBaseFilter") or []
        requested_ids = [str(entry.get("knowledgeBaseId")) for entry in kb_filter]
        chunks_by_kb: Dict[str, List[Dict[str, Any]]] = state.data.get("chunks_by_kb", {})

        # The tool reads only retrievalData[0].chunks; keep one entry per KB
        # to stay close to the real shape while exercising the same parse.
        retrieval_data = []
        for kb_id in requested_ids:
            scored = []
            for chunk in chunks_by_kb.get(kb_id, []):
                haystack = f"{chunk.get('title', '')} {chunk.get('content', '')}"
                re_rank_score = round(
                    float(chunk.get("reRankScore", 0.5)) + term_boost(question, haystack), 4
                )
                scored.append({**chunk, "reRankScore": re_rank_score})
            scored.sort(key=lambda c: c.get("reRankScore", 0), reverse=True)
            retrieval_data.append({"chunks": scored[:rank_top_n]})
        return _envelope({"retrievalData": retrieval_data})

    @router.get(f"{_IDATA_PATH}/documents/download")
    def download_document(
        userId: str = "",
        knowledgeBaseId: str = "",
        documentId: str = "",
        authorization: Optional[str] = Header(default=None),
    ) -> Response:
        """Serves the download URL shape built client-side by the tool."""
        require_bearer(authorization)
        chunks_by_kb: Dict[str, List[Dict[str, Any]]] = state.data.get("chunks_by_kb", {})
        chunk = next(
            (
                c
                for chunks in chunks_by_kb.values()
                for c in chunks
                if c.get("documentId") == documentId
            ),
            None,
        )
        if chunk is None:
            raise HTTPException(status_code=404, detail=f"Document {documentId} not found")
        filename = str(chunk.get("documentName") or documentId)
        content = f"Mock iData content for {filename}\n".encode("utf-8")
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{documentId}.bin"',
            },
        )

    return router
