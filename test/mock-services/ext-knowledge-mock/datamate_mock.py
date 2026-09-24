"""DataMate route set (mounted at /datamate, all paths under /datamate/api/...).

Contract mirrored from:
  - sdk/nexent/datamate/datamate_client.py — list (auto-paginates on
    ``data.totalPages``), files, info, retrieve; download URLs are built by
    plain concatenation ``{base}/api/data-management/datasets/{ds}/files/{fid}/download``.
  - backend/apps/file_management_app.py — the download proxy normalizes
    datamate URLs and explicitly supports a path-prefixed base by appending
    ``/api`` (_build_datamate_url_from_parts), which is exactly the layout
    served here.
  - sdk/nexent/core/tools/datamate_search_tool.py — retrieve results carry
    ``entity.{text, score, createTime, metadata, scoreDetails}``;
    ``entity.metadata`` is a JSON *string* whose ``absolute_directory_path``
    ends with the dataset id (the tool's _extract_dataset_id takes the last
    path segment).

Authorization is accepted but not validated (any value, including none) —
the real deployment's credential scheme is opaque to the product, which
merely forwards the header.
"""
import json
import mimetypes
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

from mock_common import StateStore, content_disposition, term_boost


def create_router(state: StateStore) -> APIRouter:
    router = APIRouter(prefix="/datamate")

    @router.post("/api/knowledge-base/list")
    def list_knowledge_bases(
        body: Dict[str, Any] = Body(...),
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Paged KB listing. The client loops while page <= totalPages, so
        seeds are sized (>20 KBs) to exercise the auto-pagination path."""
        page = int(body.get("page") or 1)
        size = int(body.get("size") or 20)
        kbs: List[Dict[str, Any]] = state.data.get("knowledge_bases", [])
        start = (page - 1) * size
        items = kbs[start : start + size]
        total_pages = max(1, -(-len(kbs) // size))
        return {
            "data": {
                "content": items,
                "page": page,
                "size": size,
                "totalPages": total_pages,
                "totalElements": len(kbs),
            }
        }

    @router.get("/api/knowledge-base/{knowledge_base_id}")
    def get_knowledge_base_info(
        knowledge_base_id: str,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        info: Dict[str, Dict[str, Any]] = state.data.get("kb_info_by_id", {})
        if knowledge_base_id not in info:
            raise HTTPException(status_code=404, detail=f"Knowledge base {knowledge_base_id} not found")
        return {"data": info[knowledge_base_id]}

    @router.get("/api/knowledge-base/{knowledge_base_id}/files")
    def get_knowledge_base_files(
        knowledge_base_id: str,
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        files_by_kb: Dict[str, List[Dict[str, Any]]] = state.data.get("files_by_kb", {})
        return {"data": {"content": files_by_kb.get(knowledge_base_id, [])}}

    @router.post("/api/knowledge-base/retrieve")
    def retrieve(
        body: Dict[str, Any] = Body(...),
        authorization: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Hybrid retrieval in the ``data[].entity`` envelope.

        ``entity.metadata`` is serialized to a JSON string on purpose — the
        tool's _parse_metadata accepts both str and dict, and the real
        DataMate payload carries it as a string.
        """
        query = str(body.get("query") or "")
        top_k = int(body.get("topK") or 10)
        threshold = float(body.get("threshold") or 0.0)
        kb_ids = body.get("knowledgeBaseIds") or []
        chunks_by_kb: Dict[str, List[Dict[str, Any]]] = state.data.get("chunks_by_kb", {})

        results: List[Dict[str, Any]] = []
        for kb_id in kb_ids:
            for chunk in chunks_by_kb.get(kb_id, []):
                haystack = f"{chunk.get('file_name', '')} {chunk.get('text', '')}"
                score = round(float(chunk.get("score", 0.5)) + term_boost(query, haystack), 4)
                if score < threshold:
                    continue
                results.append({
                    "entity": {
                        "text": chunk.get("text", ""),
                        "score": score,
                        "createTime": chunk.get("createTime", ""),
                        "metadata": json.dumps(chunk.get("metadata", {}), ensure_ascii=False),
                        "scoreDetails": chunk.get("scoreDetails", {}),
                    },
                })
        results.sort(key=lambda r: r["entity"]["score"], reverse=True)
        return {"data": results[:top_k]}

    @router.get("/api/data-management/datasets/{dataset_id}/files/{file_id}/download")
    def download_file(
        dataset_id: str,
        file_id: str,
        authorization: Optional[str] = Header(default=None),
    ) -> Response:
        """Serves the download URL shape consumed by the backend proxy and
        the datamate_search tool (Content-Type + Content-Disposition + 404)."""
        files_by_kb: Dict[str, List[Dict[str, Any]]] = state.data.get("files_by_kb", {})
        file_entry = next(
            (
                entry
                for entries in files_by_kb.values()
                for entry in entries
                if entry.get("fileId") == file_id
            ),
            None,
        )
        if file_entry is None:
            raise HTTPException(status_code=404, detail=f"File {file_id} not found")
        filename = str(file_entry.get("fileName") or file_id)
        content = f"Mock DataMate content for {filename} (dataset={dataset_id})\n".encode("utf-8")
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": content_disposition(filename)},
        )

    return router
