"""
Standalone mock AIDP server for Nexent AIDP management endpoint testing.

Simulates the AIDP native API endpoints consumed by backend/services/aidp_service.py:
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases          (list)
  - PUT    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases          (create)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}     (detail)
  - PATCH  /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}     (update)
  - DELETE /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}     (delete)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Upload  (upload docs)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles         (list docs)
  - POST   /KnowledgeBase/Tenants/{tenant}/Retrieval/FusionSearch  (search - preserved from reference)

All state is in-memory. Run with:
    python aidp_mgmt_mock_server.py --port 30081
"""
import argparse
import logging
import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

logger = logging.getLogger("aidp_mgmt_mock")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
)

app = FastAPI(title="AIDP Management Mock Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Configuration
# =============================================================================
EXPECTED_API_KEY = "mock-aidp-key"
TENANT = "aidp"  # tenant segment used in all path prefixes
_KB_PREFIX = f"/KnowledgeBase/Tenants/{TENANT}/KnowledgeBases"
_MODELS_PREFIX = f"/ModelService/Tenants/{TENANT}/Service"

# =============================================================================
# In-memory state
# =============================================================================
_KNOWLEDGE_BASES: Dict[str, Dict[str, Any]] = {}
_DOCUMENTS_BY_KB: Dict[str, List[Dict[str, Any]]] = {}

# =============================================================================
# Failure injection counters (used to test retry logic end-to-end)
# =============================================================================
# _FAIL_NEXT_N: how many upcoming requests should fail with _FAIL_STATUS_CODE
_FAIL_NEXT_N: int = 0
_FAIL_STATUS_CODE: int = 503
_FAIL_TOTAL_TRIGGERED: int = 0  # lifetime counter of how many 5xx/4xx we've sent


def _seed_initial_data() -> None:
    """Populate seed knowledge bases and documents for list/get testing.
    25 KBs total to exercise pagination (3 pages of 10).
    """
    seeds = [
        {"kds_id": "aidp-kb-product", "kds_name": "AIDP Product Handbook", "description": "Product documents for AIDP search capability.", "state": 4, "create_time": 1718000100, "update_time": 1718000100},
        {"kds_id": "aidp-kb-api", "kds_name": "AIDP API Guide", "description": "API and integration guide for the AIDP platform.", "state": 4, "create_time": 1718000200, "update_time": 1718000200},
        {"kds_id": "aidp-kb-faq", "kds_name": "AIDP FAQ", "description": "Frequently asked questions and troubleshooting notes.", "state": 4, "create_time": 1718000300, "update_time": 1718000300},
        {"kds_id": "aidp-kb-04", "kds_name": "Customer Support Playbook", "description": "Standard operating procedures for support teams.", "state": 4, "create_time": 1718001004, "update_time": 1718001004},
        {"kds_id": "aidp-kb-05", "kds_name": "Data Privacy Guidelines", "description": "GDPR/CCPA compliance and data handling policies.", "state": 4, "create_time": 1718001005, "update_time": 1718001005},
        {"kds_id": "aidp-kb-06", "kds_name": "Engineering Onboarding", "description": "New engineer ramp-up materials and tooling setup.", "state": 4, "create_time": 1718001006, "update_time": 1718001006},
        {"kds_id": "aidp-kb-07", "kds_name": "Frontend Style Guide", "description": "React component library and design token references.", "state": 4, "create_time": 1718001007, "update_time": 1718001007},
        {"kds_id": "aidp-kb-08", "kds_name": "HR Policy Handbook", "description": "Leave, benefits, and company culture guidelines.", "state": 4, "create_time": 1718001008, "update_time": 1718001008},
        {"kds_id": "aidp-kb-09", "kds_name": "Incident Response Runbook", "description": "On-call procedures and escalation matrices.", "state": 4, "create_time": 1718001009, "update_time": 1718001009},
        {"kds_id": "aidp-kb-10", "kds_name": "Java Migration Notes", "description": "Legacy Java service migration to microservices.", "state": 4, "create_time": 1718001010, "update_time": 1718001010},
        {"kds_id": "aidp-kb-11", "kds_name": "Kubernetes Operations", "description": "Cluster management, scaling, and maintenance.", "state": 4, "create_time": 1718001011, "update_time": 1718001011},
        {"kds_id": "aidp-kb-12", "kds_name": "Localization Guide", "description": "i18n/l10n standards for multi-region releases.", "state": 4, "create_time": 1718001012, "update_time": 1718001012},
        {"kds_id": "aidp-kb-13", "kds_name": "Marketing Collateral", "description": "Brand assets, press kits, and campaign materials.", "state": 4, "create_time": 1718001013, "update_time": 1718001013},
        {"kds_id": "aidp-kb-14", "kds_name": "Network Architecture", "description": "VPC topology, load balancing, and DNS configuration.", "state": 4, "create_time": 1718001014, "update_time": 1718001014},
        {"kds_id": "aidp-kb-15", "kds_name": "Observability Stack", "description": "Metrics, logging, and distributed tracing setup.", "state": 4, "create_time": 1718001015, "update_time": 1718001015},
        {"kds_id": "aidp-kb-16", "kds_name": "Performance Benchmarks", "description": "Load test results and SLO reports across services.", "state": 4, "create_time": 1718001016, "update_time": 1718001016},
        {"kds_id": "aidp-kb-17", "kds_name": "QA Test Plans", "description": "Regression suites and release gating checklists.", "state": 4, "create_time": 1718001017, "update_time": 1718001017},
        {"kds_id": "aidp-kb-18", "kds_name": "Release Notes Archive", "description": "Changelog and release communication templates.", "state": 4, "create_time": 1718001018, "update_time": 1718001018},
        {"kds_id": "aidp-kb-19", "kds_name": "Security Audit Reports", "description": "Penetration test findings and remediation trackers.", "state": 4, "create_time": 1718001019, "update_time": 1718001019},
        {"kds_id": "aidp-kb-20", "kds_name": "Terraform Modules", "description": "Reusable IaC modules for infrastructure provisioning.", "state": 4, "create_time": 1718001020, "update_time": 1718001020},
        {"kds_id": "aidp-kb-21", "kds_name": "User Research Insights", "description": "Persona studies, usability tests, and journey maps.", "state": 4, "create_time": 1718001021, "update_time": 1718001021},
        {"kds_id": "aidp-kb-22", "kds_name": "Vendor Contracts", "description": "SaaS licensing agreements and SLA commitments.", "state": 4, "create_time": 1718001022, "update_time": 1718001022},
        {"kds_id": "aidp-kb-23", "kds_name": "Workflow Automation", "description": "Zapier/n8n integrations and scheduling playbooks.", "state": 4, "create_time": 1718001023, "update_time": 1718001023},
        {"kds_id": "aidp-kb-24", "kds_name": "Cross-Platform Builds", "description": "macOS/Windows/Linux build matrix and signing keys.", "state": 4, "create_time": 1718001024, "update_time": 1718001024},
        {"kds_id": "aidp-kb-25", "kds_name": "Year in Review 2024", "description": "Annual retrospective and OKR outcomes.", "state": 4, "create_time": 1718001025, "update_time": 1718001025},
    ]
    for kb in seeds:
        _KNOWLEDGE_BASES[kb["kds_id"]] = kb
        _DOCUMENTS_BY_KB[kb["kds_id"]] = []

    # Seed some documents for the FAQ KB so list_docs is non-empty by default.
    _DOCUMENTS_BY_KB["aidp-kb-faq"] = [
        {
            "file_ino_no": "file-faq-001",
            "file_name": "常见问题汇总.txt",
            "file_size": 2048,
            "file_type": "txt",
            "create_time": 1718000400,
        },
        {
            "file_ino_no": "file-faq-002",
            "file_name": "troubleshooting.md",
            "file_size": 4096,
            "file_type": "md",
            "create_time": 1718000500,
        },
    ]


_seed_initial_data()


# =============================================================================
# Request Models
# =============================================================================
class CreateKbBody(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    embedding_model: Optional[str] = None
    is_multimodal: Optional[bool] = None
    vision_model: Optional[str] = None


class UpdateKbBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class MetadataCondition(BaseModel):
    logical_operator: Literal["and", "or"] = "and"
    conditions: List[Dict[str, Any]] = Field(default_factory=list)


class FusionSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    kds_list: List[str] = Field(min_length=1, max_length=10)
    search_method: Literal["hybrid_search", "vector_search", "full_text_search"] = "hybrid_search"
    reranking_enable: bool = False
    reranking_mode: Optional[Literal["performance", "high_accuracy"]] = None
    rewrite_enable: bool = False
    related_search_enable: bool = False
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    top_k: int = Field(10, ge=1, le=100)
    multi_modal: bool = False
    metadata_condition: Optional[MetadataCondition] = None


# =============================================================================
# Auth helper
# =============================================================================
def _check_auth(authorization: Optional[str]) -> None:
    """Validate Bearer token against the expected API key."""
    expected = f"Bearer {EXPECTED_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# =============================================================================
# Failure injection middleware (tests retry logic end-to-end)
# =============================================================================
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse


class FailNextMiddleware(BaseHTTPMiddleware):
    """Intercepts real AIDP calls (under /KnowledgeBase/) and returns a
    configured error status for the next N requests, then lets them through.
    Use POST /_mock/fail-next?n=2&status=503 to schedule the next 2 requests
    to fail with 503, then verify the client retries them successfully.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        global _FAIL_NEXT_N, _FAIL_TOTAL_TRIGGERED
        # Only intercept the real AIDP-looking endpoints (not the admin ones)
        if request.url.path.startswith("/KnowledgeBase"):
            if _FAIL_NEXT_N > 0:
                _FAIL_NEXT_N -= 1
                _FAIL_TOTAL_TRIGGERED += 1
                logger.info(
                    "MOCK INJECT  %d failures remaining, returning %d on %s",
                    _FAIL_NEXT_N, _FAIL_STATUS_CODE, request.url.path,
                )
                return JSONResponse(
                    status_code=_FAIL_STATUS_CODE,
                    content={
                        "error": "mock-injected failure for retry testing",
                        "status": _FAIL_STATUS_CODE,
                    },
                )
        return await call_next(request)


app.add_middleware(FailNextMiddleware)


# =============================================================================
# Admin-only endpoints: control failure injection
# =============================================================================
@app.post("/_mock/fail-next")
def schedule_failures(
    n: int = Query(1, ge=0, description="Number of upcoming AIDP requests to fail"),
    status: int = Query(503, description="HTTP status code to return on each failure"),
) -> JSONResponse:
    """Schedule the next N real AIDP endpoints (GET/POST /KnowledgeBase/...) to
    fail with the given status code. Returns 200 with the current plan.

    Example — simulate 2 transient 503 errors before the client succeeds:
        curl -X POST 'http://localhost:30081/_mock/fail-next?n=2&status=503'
    Then trigger any AIDP-backed action and watch the client retry logic kick in.
    """
    global _FAIL_NEXT_N, _FAIL_STATUS_CODE
    _FAIL_NEXT_N = n
    _FAIL_STATUS_CODE = status
    logger.info("MOCK SCHEDULE  next %d requests will return status %d", n, status)
    return JSONResponse(content={
        "fail_next": _FAIL_NEXT_N,
        "status_code": _FAIL_STATUS_CODE,
        "total_triggered": _FAIL_TOTAL_TRIGGERED,
    })


@app.get("/_mock/fail-status")
def get_fail_status() -> JSONResponse:
    """Check the current failure-injection state. Does not mutate counters."""
    return JSONResponse(content={
        "fail_next": _FAIL_NEXT_N,
        "status_code": _FAIL_STATUS_CODE,
        "total_triggered": _FAIL_TOTAL_TRIGGERED,
    })


@app.post("/_mock/fail-reset")
def reset_failures() -> JSONResponse:
    """Reset the failure-injection counters to zero without restarting the server."""
    global _FAIL_NEXT_N, _FAIL_TOTAL_TRIGGERED, _FAIL_STATUS_CODE
    _FAIL_NEXT_N = 0
    _FAIL_STATUS_CODE = 503
    _FAIL_TOTAL_TRIGGERED = 0
    logger.info("MOCK RESET  failure injection counters cleared")
    return JSONResponse(content={
        "fail_next": _FAIL_NEXT_N,
        "status_code": _FAIL_STATUS_CODE,
        "total_triggered": _FAIL_TOTAL_TRIGGERED,
    })


# =============================================================================
# Knowledge Base CRUD
# =============================================================================


@app.get(_KB_PREFIX)
def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """List knowledge bases with pagination + next_link (matches AIDP shape)."""
    _check_auth(authorization)

    all_items = list(_KNOWLEDGE_BASES.values())
    start = (page - 1) * page_size
    end = start + page_size
    # Enrich each item with document_count (same as detail endpoint does)
    enriched = [{**kb, "document_count": len(_DOCUMENTS_BY_KB.get(kb["kds_id"], []))} for kb in all_items]
    items = enriched[start:end]

    next_link = None
    if end < len(all_items):
        next_link = f"{_KB_PREFIX}?page={page + 1}&page_size={page_size}"

    logger.info("LIST  page=%d page_size=%d returned=%d total=%d", page, page_size, len(items), len(all_items))
    # Real AIDP returns `total_count` = current page count (len(items)), not
    # the true total. Use the Count endpoint for the true total.
    return JSONResponse(content={
        "value": items,
        "total_count": len(items),
        "next_link": next_link,
    })


@app.post(f"{_KB_PREFIX}/{{kds_id}}/Count")
def count_knowledge_bases(
    kds_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Count knowledge bases. AIDP uses POST .../KnowledgeBases/{kds_id}/Count."""
    _check_auth(authorization)
    count = len(_KNOWLEDGE_BASES)
    logger.info("COUNT  kds_id=%s count=%d", kds_id, count)
    return JSONResponse(content={"count": count})


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Count")
def count_documents(
    kds_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Count documents in a knowledge base.
    AIDP uses POST .../KnowledgeBases/{kds_id}/KnowledgeFiles/Count with
    empty body, returning {"count": <int>}.
    """
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    count = len(_DOCUMENTS_BY_KB.get(kds_id, []))
    logger.info("COUNT DOCS  kds_id=%s count=%d", kds_id, count)
    return JSONResponse(content={"count": count})


@app.put(_KB_PREFIX)
def create_knowledge_base(
    body: CreateKbBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Create a new knowledge base. AIDP uses PUT on the collection endpoint."""
    _check_auth(authorization)

    kds_id = f"aidp-kb-{uuid.uuid4().hex[:8]}"
    now = int(time.time())
    new_kb = {
        "kds_id": kds_id,
        "kds_name": body.name,
        "description": body.description or "",
        "state": 4,
        "create_time": now,
        "update_time": now,
    }
    if body.embedding_model:
        new_kb["embedding_model"] = body.embedding_model
    if body.is_multimodal is not None:
        new_kb["is_multimodal"] = body.is_multimodal
    if body.vision_model:
        new_kb["vision_model"] = body.vision_model

    _KNOWLEDGE_BASES[kds_id] = new_kb
    _DOCUMENTS_BY_KB[kds_id] = []

    logger.info("CREATE  kds_id=%s name=%r", kds_id, body.name)
    return JSONResponse(content=new_kb)


@app.get(f"{_KB_PREFIX}/{{kds_id}}")
def get_knowledge_base(
    kds_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Get a single knowledge base by ID."""
    _check_auth(authorization)

    kb = _KNOWLEDGE_BASES.get(kds_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    # Augment with document count for richer responses
    docs = _DOCUMENTS_BY_KB.get(kds_id, [])
    result = {**kb, "document_count": len(docs)}

    logger.info("GET  kds_id=%s", kds_id)
    return JSONResponse(content=result)


@app.patch(f"{_KB_PREFIX}/{{kds_id}}")
def update_knowledge_base(
    kds_id: str,
    body: UpdateKbBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Update name/description of a knowledge base. AIDP uses PATCH."""
    _check_auth(authorization)

    kb = _KNOWLEDGE_BASES.get(kds_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    if body.name is not None:
        kb["kds_name"] = body.name
    if body.description is not None:
        kb["description"] = body.description
    kb["update_time"] = int(time.time())

    logger.info("UPDATE  kds_id=%s name=%r description=%r", kds_id, body.name, body.description)
    return JSONResponse(content=kb)


@app.delete(f"{_KB_PREFIX}/{{kds_id}}")
def delete_knowledge_base(
    kds_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Delete a knowledge base and its documents."""
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    del _KNOWLEDGE_BASES[kds_id]
    _DOCUMENTS_BY_KB.pop(kds_id, None)

    logger.info("DELETE  kds_id=%s", kds_id)
    return JSONResponse(content={"success": True})


# =============================================================================
# Document Management
# =============================================================================


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Upload")
async def upload_documents(
    kds_id: str,
    files: List[UploadFile] = File(...),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Upload documents to a knowledge base. AIDP uses form-data file upload."""
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    success_docs: List[Dict[str, Any]] = []
    failed: List[Dict[str, str]] = []
    for f in files:
        try:
            content = await f.read()
            file_ino_no = f"file-{uuid.uuid4().hex[:12]}"
            doc = {
                "file_ino_no": file_ino_no,
                "file_name": f.filename or "unknown",
                "file_size": len(content),
                "file_type": (f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else "bin"),
                "create_time": int(time.time()),
            }
            _DOCUMENTS_BY_KB.setdefault(kds_id, []).append(doc)
            success_docs.append(doc)
            logger.info("UPLOAD  kds_id=%s file=%s size=%d", kds_id, f.filename, len(content))
        except Exception as e:
            failed.append({"name": f.filename or "unknown", "error": str(e)})
            logger.warning("UPLOAD FAIL  kds_id=%s file=%s error=%s", kds_id, f.filename, e)

    return JSONResponse(content={
        "success_count": len(success_docs),
        "failed_count": len(failed),
        "errors": [f"{d['name']}: {d['error']}" for d in failed],
        "document_ids": [d["file_ino_no"] for d in success_docs],
    })


@app.get(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles")
def list_documents(
    kds_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """List documents in a knowledge base with pagination."""
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    all_docs = _DOCUMENTS_BY_KB.get(kds_id, [])
    start = (page - 1) * page_size
    end = start + page_size
    items = all_docs[start:end]

    # Real AIDP returns `next_link` as the authoritative "more pages exist"
    # signal. When there are no more docs, next_link is simply absent.
    # `total_count` is the current page count, not the true total.
    next_link = None
    if end < len(all_docs):
        next_link = f"{_KB_PREFIX}/{kds_id}/KnowledgeFiles?page={page + 1}&page_size={page_size}"

    logger.info("LIST DOCS  kds_id=%s page=%d returned=%d total=%d", kds_id, page, len(items), len(all_docs))
    return JSONResponse(content={
        "value": items,
        "total_count": len(items),
        "next_link": next_link,
    })


# =============================================================================
# FusionSearch (preserved from reference mock)
# =============================================================================

# External online image URLs for multi-modal search results
_MOCK_IMAGE_URLS = [
    "https://vcg02.cfp.cn/creative/vcg/nowater800/new/VCG211574918167.jpeg",
    "https://www.bing.com/th/id/OIP.eAfcHNjS5p2djMc0zAUAXQHaLH?w=193&h=290&c=8&rs=1&qlt=90&o=6&pid=3.1&rm=2",
]

_CHUNKS_BY_KB: Dict[str, List[Dict[str, Any]]] = {
    "aidp-kb-product": [
        {
            "id": 10001,
            "score": 0.96,
            "title": "AIDP产品介绍.pdf",
            "text": "AIDP Search provides low-latency retrieval across selected enterprise knowledge bases.",
            "metadata": {"knowledge_base_id": "aidp-kb-product", "section": "overview"},
            "chunk_type": "text",
            "file_url": "",
            "pages": [1],
        },
    ],
    "aidp-kb-faq": [
        {
            "id": 30001,
            "score": 0.93,
            "title": "常见问题汇总.txt",
            "text": "If no results are returned, verify the selected knowledge base IDs and API key.",
            "metadata": {"knowledge_base_id": "aidp-kb-faq", "section": "troubleshooting"},
            "chunk_type": "text",
            "file_url": "",
            "pages": [1],
        },
        {
            "id": 30002,
            "score": 0.985,
            "title": "肝脏医学影像.jpg",
            "text": "Liver image for validating AIDP multi-modal retrieval image return pathway.",
            "metadata": {"knowledge_base_id": "aidp-kb-faq", "section": "liver-image-demo"},
            "chunk_type": "image",
            "file_url": _MOCK_IMAGE_URLS[0],
            "pages": [6],
        },
    ],
}


def _match_metadata(chunk: Dict[str, Any], condition: Optional[MetadataCondition]) -> bool:
    if not condition or not condition.conditions:
        return True
    meta = chunk.get("metadata", {})
    results = []
    for c in condition.conditions:
        field = c.get("name", "")
        op = c.get("comparison_operator", "contains")
        val = c.get("value", "")
        cv = str(meta.get(field, ""))
        if op == "contains":
            results.append(val.lower() in cv.lower())
        elif op == "equals":
            results.append(cv.lower() == val.lower())
        elif op == "not_equals":
            results.append(cv.lower() != val.lower())
        elif op == "empty":
            results.append(cv in ("", "None"))
        elif op == "not_empty":
            results.append(cv not in ("", "None"))
        else:
            results.append(False)
    return all(results) if condition.logical_operator == "and" else any(results)


@app.post(f"/KnowledgeBase/Tenants/{TENANT}/Retrieval/FusionSearch")
def fusion_search(
    request: FusionSearchRequest,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Handle FusionSearch requests (same as reference mock)."""
    _check_auth(authorization)

    query_terms = [t.strip().lower() for t in request.query.split() if t.strip()]
    results: List[Dict[str, Any]] = []

    for kb_id in request.kds_list:
        for chunk in _CHUNKS_BY_KB.get(kb_id, []):
            if not _match_metadata(chunk, request.metadata_condition):
                continue
            if not request.multi_modal and chunk.get("chunk_type") == "image":
                continue

            haystack = f"{chunk.get('title', '')} {chunk.get('text', '')}".lower()
            boost = min(0.05 * sum(1 for t in query_terms if t in haystack), 0.15)
            score = round(float(chunk.get("score", 0.5)) + boost, 4)
            if score < request.score_threshold:
                continue

            item = {
                "id": chunk["id"],
                "score": score,
                "title": chunk["title"],
                "text": chunk["text"],
                "metadata": {
                    **chunk.get("metadata", {}),
                    "_search_config": {
                        "search_method": request.search_method,
                        "reranking_enable": request.reranking_enable,
                    },
                },
            }
            if request.multi_modal:
                item["chunk_type"] = chunk.get("chunk_type", "text")
                item["file_url"] = chunk.get("file_url", "")
                item["pages"] = chunk.get("pages", [])
            results.append(item)

    results.sort(key=lambda x: x["score"], reverse=True)
    final = results[: request.top_k]

    logger.info("SEARCH  query=%r kds=%r returned=%d", request.query, request.kds_list, len(final))
    return JSONResponse(content={"result": final, "total_return_count": len(final)})


# =============================================================================
# ModelService — lists VLM/LLM models applicable to AIDP applications
# =============================================================================

# Seeded models mirror the shape of real AIDP ModelService responses. The
# ``application`` field determines which AIDP app a model can serve (the
# backend's ``_is_kb_applicable`` post-filters by "All" or the requested app).
_MOCK_MODELS: List[Dict[str, Any]] = [
    {
        "api_key": "",
        "application": "All",
        "created_at": 1782716626,
        "max_tokens": 32768,
        "model_name": "model_1",
        "properties": {"description": "General purpose LLM.", "model_type": "external"},
        "service": "llm",
        "temperature": 0.6,
        "top_k": 10,
        "top_p": 0.8,
        "url": "http://localhost:11025/v1",
    },
    {
        "application": ["KnowledgeBase"],
        "model_name": "Qwen3-VL-8B-Instruct",
        "properties": {"description": "Vision-language model served internally for caption generation.", "model_type": "internal"},
        "service": "llm",
        "url": "http://caption-service.model-service.svc.cluster.local:8111/v1/chat/completions",
    },
    {
        "api_key": "",
        "application": "All",
        "created_at": 1783070801,
        "max_tokens": 32768,
        "model_name": "Qwen3-VL-32B-Instruct",
        "properties": {"description": "Larger vision-language model for high-quality captioning.", "model_type": "external"},
        "service": "llm",
        "temperature": 0.6,
        "top_k": 10,
        "top_p": 0.8,
        "url": "http://localhost:11025/v1",
    },
    {
        "api_key": "",
        "application": "All",
        "created_at": 1783474808,
        "max_tokens": 32780,
        "model_name": "InternVL2-26B",
        "properties": {"description": "Open-source multimodal model.", "model_type": "external"},
        "service": "llm",
        "temperature": 1.5,
        "top_k": 50,
        "top_p": 0.5,
        "url": "https://localhost:11443/v1",
    },
    # The following model targets a different application ("DocumentParsing")
    # and must be FILTERED OUT by the backend's _is_kb_applicable() filter.
    {
        "api_key": "",
        "application": ["DocumentParsing"],
        "created_at": 1783062626,
        "model_name": "doc-parser-only",
        "properties": {"description": "Should NOT appear for KnowledgeBase.", "model_type": "external"},
        "service": "llm",
    },
]


@app.get(_MODELS_PREFIX)
def list_models(
    service: str = Query("llm"),
    app: str = Query("KnowledgeBase"),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Return the list of registered models. Real AIDP does NOT filter by the
    ``app`` query param — callers must post-filter by ``application``. The
    backend (aidp_service._is_kb_applicable) does this, so we just dump the
    raw seed data here.
    """
    _check_auth(authorization)
    logger.info("LIST MODELS  service=%s app=%s returned=%d", service, app, len(_MOCK_MODELS))
    return JSONResponse(content={
        "service": service,
        "models": _MOCK_MODELS,
    })


# =============================================================================
# System endpoints
# =============================================================================


@app.get("/health")
def health() -> Dict[str, Any]:
    """Liveness probe."""
    return {
        "status": "ok",
        "platform": "aidp-mock",
        "version": "1.0.0",
        "knowledge_bases_count": len(_KNOWLEDGE_BASES),
    }


@app.post("/_reset")
def reset_state() -> Dict[str, str]:
    """Reset in-memory state back to seeds (useful between test runs)."""
    _KNOWLEDGE_BASES.clear()
    _DOCUMENTS_BY_KB.clear()
    _seed_initial_data()
    logger.info("RESET  state restored to seeds")
    return {"status": "reset"}


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIDP Management Mock Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=30081, help="Bind port (default: 30081)")
    parser.add_argument("--api-key", default=EXPECTED_API_KEY, help="Expected Bearer API key")
    args = parser.parse_args()

    EXPECTED_API_KEY = args.api_key

    import uvicorn

    print(f"\nAIDP Mock Server starting on http://{args.host}:{args.port}")
    print(f"  Tenant path prefix: {_KB_PREFIX}")
    print(f"  Expected API key:   Bearer {EXPECTED_API_KEY}")
    print(f"  Seed KBs:           {len(_KNOWLEDGE_BASES)} pre-populated")
    print(f"  POST /_reset to restore initial state\n")

    uvicorn.run(app, host=args.host, port=args.port)
