"""Standalone mock AIDP server for Nexent end-to-end testing."""
import logging
from typing import Any, Dict, List, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

logger = logging.getLogger("aidp_mock_server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AIDP Mock Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_EXPECTED_API_KEY = "mock-aidp-key"

# External online image URLs for multi-modal search results
_MOCK_IMAGE_URLS = [
    "https://vcg02.cfp.cn/creative/vcg/nowater800/new/VCG211574918167.jpeg?x-oss-process=image/format,webp",
    "https://www.bing.com/th/id/OIP.eAfcHNjS5p2djMc0zAUAXQHaLH?w=193&h=290&c=8&rs=1&qlt=90&o=6&pid=3.1&rm=2",
]


# =============================================================================
# Mock Knowledge Bases
# =============================================================================
_KNOWLEDGE_BASES: List[Dict[str, Any]] = [
    {
        "create_time": 1718000100,
        "description": "Product documents for AIDP search capability.",
        "kds_id": "aidp-kb-product",
        "kds_name": "AIDP Product Handbook",
        "kms_config_str": '{"chunk_token_num": 1024}',
        "person_space": 0,
        "state": 4,
        "vector_coll_name": "aidp_product_handbook",
        "current_cap": 128.0,
        "max_cap": 1024.0,
        "role": "reader",
    },
    {
        "create_time": 1718000200,
        "description": "API and integration guide for the AIDP platform.",
        "kds_id": "aidp-kb-api",
        "kds_name": "AIDP API Guide",
        "kms_config_str": '{"chunk_token_num": 512}',
        "person_space": 0,
        "state": 4,
        "vector_coll_name": "aidp_api_guide",
        "current_cap": 64.0,
        "max_cap": 512.0,
        "role": "editor",
    },
    {
        "create_time": 1718000300,
        "description": "Frequently asked questions and troubleshooting notes.",
        "kds_id": "aidp-kb-faq",
        "kds_name": "AIDP FAQ",
        "kms_config_str": '{"chunk_token_num": 768}',
        "person_space": 0,
        "state": 4,
        "vector_coll_name": "aidp_faq",
        "current_cap": 32.0,
        "max_cap": 256.0,
        "role": "reader",
    },
]

# =============================================================================
# Mock Chunks - keyed by knowledge base ID
# Each chunk has integer id, matching the AIDP real API response format
# title = source file name, text = chunk content
# =============================================================================
_CHUNKS_BY_KB: Dict[str, List[Dict[str, Any]]] = {
    "aidp-kb-product": [
        {
            "id": 10001,
            "score": 0.96,
            "title": "AIDP产品介绍.pdf",
            "text": "AIDP Search provides low-latency retrieval across selected enterprise knowledge bases and supports configurable reranking.",
            "metadata": {"knowledge_base_id": "aidp-kb-product", "section": "overview", "author": "product-team"},
            "chunk_type": "text",
            "file_url": "",
            "pages": [1],
        },
        {
            "id": 10002,
            "score": 0.89,
            "title": "系统架构文档.docx",
            "text": "The search flow includes knowledge base selection, query rewrite, candidate retrieval, and optional reranking before final answer generation.",
            "metadata": {"knowledge_base_id": "aidp-kb-product", "section": "architecture", "author": "product-team"},
            "chunk_type": "text",
            "file_url": "",
            "pages": [3],
        },
    ],
    "aidp-kb-api": [
        {
            "id": 20001,
            "score": 0.97,
            "title": "API快速入门.md",
            "text": "Configure base_url and api_key, then call FusionSearch with query, kds_list, search_method, and top_k to retrieve ranked chunks.",
            "metadata": {"knowledge_base_id": "aidp-kb-api", "section": "quick-start", "api_version": "v1"},
            "chunk_type": "text",
            "file_url": "",
            "pages": [2],
        },
        {
            "id": 20002,
            "score": 0.91,
            "title": "API参数说明.xlsx",
            "text": "Supported search methods are hybrid_search, vector_search, and full_text_search. You can also enable reranking and query rewrite.",
            "metadata": {"knowledge_base_id": "aidp-kb-api", "section": "parameters", "api_version": "v1"},
            "chunk_type": "table",
            "file_url": "",
            "pages": [4],
        },
    ],
    "aidp-kb-faq": [
        {
            "id": 30001,
            "score": 0.93,
            "title": "常见问题汇总.txt",
            "text": "If no results are returned, verify the selected knowledge base IDs, API key, and whether the knowledge base state is active.",
            "metadata": {"knowledge_base_id": "aidp-kb-faq", "section": "troubleshooting", "priority": "high"},
            "chunk_type": "text",
            "file_url": "",
            "pages": [1],
        },
        {
            "id": 30002,
            "score": 0.88,
            "title": "界面截图示例.png",
            "text": "Use the tool test panel to send a natural language query and inspect the ranked retrieval chunks returned by the mock server.",
            "metadata": {"knowledge_base_id": "aidp-kb-faq", "section": "ui-example"},
            "chunk_type": "image",
            "file_url": _MOCK_IMAGE_URLS[0],
            "pages": [5],
        },
        {
            "id": 30003,
            "score": 0.985,
            "title": "肝脏医学影像.jpg",
            "text": "This is a liver image for validating the AIDP multi-modal retrieval image return pathway. It tests whether image URLs in search results can be correctly rendered on the frontend.",
            "metadata": {"knowledge_base_id": "aidp-kb-faq", "section": "liver-image-demo", "keywords": ["liver", "image", "multi-modal", "search"]},
            "chunk_type": "image",
            "file_url": _MOCK_IMAGE_URLS[1],
            "pages": [6],
        },
    ],
}


# =============================================================================
# Request/Response Models
# =============================================================================
class MetadataCondition(BaseModel):
    logical_operator: Literal["and", "or"] = Field(default="and")
    conditions: List[Dict[str, Any]] = Field(default_factory=list)


class FusionSearchRequest(BaseModel):
    query: str = Field(min_length=1, description="待检索的问题")
    kds_list: List[str] = Field(min_length=1, max_length=10, description="检索的知识库ID列表")
    search_method: Literal["hybrid_search", "vector_search", "full_text_search"] = Field(
        default="hybrid_search", description="检索方法"
    )
    reranking_enable: bool = Field(default=False, description="是否重排序")
    reranking_mode: Literal["performance", "high_accuracy"] | None = Field(
        default=None, description="重排序模式"
    )
    rewrite_enable: bool = Field(default=False, description="是否启用黑话改写query")
    related_search_enable: bool = Field(default=False, description="是否启用关联Chunk检索")
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="相似度阈值")
    top_k: int = Field(default=10, ge=1, le=100, description="匹配结果数")
    multi_modal: bool = Field(default=False, description="是否多模态检索")
    metadata_condition: MetadataCondition | None = Field(default=None, description="元数据过滤条件")


# =============================================================================
# Helper Functions
# =============================================================================
def _validate_auth(authorization: str | None) -> None:
    expected_header = f"Bearer {_EXPECTED_API_KEY}"
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _match_metadata_condition(chunk: Dict[str, Any], condition: MetadataCondition | None) -> bool:
    """Check if chunk metadata matches the given condition."""
    if not condition or not condition.conditions:
        return True

    chunk_metadata = chunk.get("metadata", {})
    results: List[bool] = []

    for cond in condition.conditions:
        field_name = cond.get("name", "")
        operator = cond.get("comparison_operator", "contains")
        value = cond.get("value", "")

        chunk_value = str(chunk_metadata.get(field_name, ""))

        if operator == "contains":
            matched = value.lower() in chunk_value.lower()
        elif operator == "equals":
            matched = chunk_value.lower() == value.lower()
        elif operator == "not_equals":
            matched = chunk_value.lower() != value.lower()
        elif operator == "empty":
            matched = chunk_value == "" or chunk_value == "None"
        elif operator == "not_empty":
            matched = chunk_value != "" and chunk_value != "None"
        else:
            matched = False

        results.append(matched)

    if condition.logical_operator == "and":
        return all(results)
    else:
        return any(results)


def _score_chunk(chunk: Dict[str, Any], query_terms: List[str]) -> float:
    """Calculate relevance score based on query term matching."""
    base_score = float(chunk.get("score", 0.5))
    haystack = f"{chunk.get('title', '')} {chunk.get('text', '')}".lower()

    matched_count = sum(1 for term in query_terms if term.lower() in haystack)
    boost = min(0.05 * matched_count, 0.15)

    return round(base_score + boost, 4)


# =============================================================================
# API Endpoints
# =============================================================================
@app.get("/KnowledgeBase/Tenants/aidp/KnowledgeBases")
def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    _validate_auth(authorization)

    start = (page - 1) * page_size
    end = start + page_size
    items = _KNOWLEDGE_BASES[start:end]
    next_link = None
    if end < len(_KNOWLEDGE_BASES):
        next_link = f"/KnowledgeBase/Tenants/aidp/KnowledgeBases?page={page + 1}&page_size={page_size}"

    return JSONResponse(content={
        "value": items,
        "next_link": next_link,
        "total_count": len(_KNOWLEDGE_BASES),
    })


@app.post("/KnowledgeBase/Tenants/aidp/Retrieval/FusionSearch")
def fusion_search(
    request: FusionSearchRequest,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Handle FusionSearch requests from AIDP search tool."""
    _validate_auth(authorization)

    query_terms = [t.strip() for t in request.query.split() if t.strip()]
    matched_results: List[Dict[str, Any]] = []

    for kb_id in request.kds_list:
        chunks = _CHUNKS_BY_KB.get(kb_id, [])

        for chunk in chunks:
            if not _match_metadata_condition(chunk, request.metadata_condition):
                continue

            if not request.multi_modal and chunk.get("chunk_type") == "image":
                continue

            score = _score_chunk(chunk, query_terms)

            if score < request.score_threshold:
                continue

            result_item = {
                "id": chunk["id"],
                "score": score,
                "title": chunk["title"],
                "text": chunk["text"],
                "metadata": {
                    **chunk.get("metadata", {}),
                    "_search_config": {
                        "search_method": request.search_method,
                        "reranking_enable": request.reranking_enable,
                        "reranking_mode": request.reranking_mode,
                        "rewrite_enable": request.rewrite_enable,
                        "related_search_enable": request.related_search_enable,
                    },
                },
            }

            if request.multi_modal:
                result_item["chunk_type"] = chunk.get("chunk_type", "text")
                result_item["file_url"] = chunk.get("file_url", "")
                result_item["pages"] = chunk.get("pages", [])

            matched_results.append(result_item)

    matched_results.sort(key=lambda x: x["score"], reverse=True)
    final_results = matched_results[: request.top_k]

    logger.info(
        "FusionSearch query=%r kds_list=%r method=%s multi_modal=%s returned=%d",
        request.query,
        request.kds_list,
        request.search_method,
        request.multi_modal,
        len(final_results),
    )

    return JSONResponse(content={
        "result": final_results,
        "total_return_count": len(final_results),
    })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=30081)
