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
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Channels               (ingestion channels)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/History (all-status file history)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Remove  (remove docs)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Retry  (retry failed docs)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Download (download doc)
  - POST   /KnowledgeBase/Tenants/{tenant}/Retrieval/FusionSearch  (search - preserved from reference)

Document status simulation (drives the "processing status" UI):
  * The CLI delays upload responses by 10 seconds to expose the upload UI's
    waiting state. Override with ``--upload-seconds 0`` or at runtime with
    ``POST /_mock/upload-seconds?seconds=N``. This delays the AIDP response,
    not the browser-to-Nexent request body transfer.
  * Uploaded documents start as ``PROCESSING`` and flip to ``COMPLETED`` once
    ``_PROCESSING_SECONDS`` have elapsed, so polling behaviour can be observed
    end to end. Tune it with ``POST /_mock/processing-seconds?seconds=N``.
  * ``POST /_mock/doc-status`` (body ``{kds_id, file_ino_no, status}``) forces one
    document into any status without waiting for the timer, including the
    non-terminal ``UPLOADING`` / ``EXTRACTING`` stages.
  * ``GET .../KnowledgeFiles`` keeps returning COMPLETED documents only (mirrors
    real AIDP), while ``POST .../KnowledgeFiles/History`` returns every status.
  * ``POST .../KnowledgeFiles/History`` returns records from the last 30 days
    and supports page, page_size, file-name keyword, and numeric status filters.
    Tune the default page size with ``POST /_mock/history-page-size?size=N``.

Knowledge base + document state is persisted to ``_state/knowledge_bases.json``
(next to this file). On restart the mock loads the file, so KBs created by
tests or frontend sessions survive across restarts without re-creation
(which was otherwise the cause of spurious 404s in list endpoints against
stale Nexent permission rows). ``POST /_reset`` clears the file and
rebuilds the seed data. ``AIDP_MOCK_STATE_FILE`` can point to an existing local
state file when testing another checkout. On startup, the mock upgrades the
existing FAQ seed to a fully populated Chinese knowledge base with recent file
and upload-task examples without clearing other persisted state. Run with:
    python aidp_mgmt_mock_server.py --port 30081
"""
import argparse
import asyncio
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

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

# Document status constants mirroring the real AIDP vocabulary.
STATUS_PROCESSING = "PROCESSING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
_TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, 1, 3, 5, "1", "3", "5"}

# One ingestion channel per knowledge base, exposed at the KB-scoped path the
# real AIDP uses (``.../KnowledgeBases/{kds_id}/Channels``). ``src_dir`` embeds
# the KB id, which is how this mock maps a History ``dir_path`` back to its
# documents. The tenant-scoped variant is deliberately NOT served: a wrong path
# in the adapter must fail here exactly as it fails against AIDP.
_CHANNEL_ROOT = "/aidp/knowledge"

# Seconds an uploaded document stays PROCESSING before turning COMPLETED.
# Overridable at runtime through POST /_mock/processing-seconds.
_PROCESSING_SECONDS = 8.0

# Response latency per upload request; CLI defaults to 10 seconds for UI review.
# Imported test apps start without latency and opt in through the mock endpoint.
_UPLOAD_SECONDS = 0.0

# Default number of history records returned by each AIDP page.
_HISTORY_PAGE_SIZE = 10

# Directory for persisted runtime state. Lives next to this file so the mock
# is self-contained (no absolute paths) and stays out of version control via
# ``.gitignore``. Only KB + document state is persisted; failure-injection
# counters deliberately stay in-memory so each restart starts with a clean
# failure plan.
_DEFAULT_STATE_FILE = Path(__file__).with_suffix("").with_name("_state") / "knowledge_bases.json"
_STATE_FILE = Path(os.environ.get("AIDP_MOCK_STATE_FILE", str(_DEFAULT_STATE_FILE))).expanduser()
_STATE_DIR = _STATE_FILE.parent

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
        {
            "kds_id": "aidp-kb-faq",
            "kds_name": "政务服务与城市治理知识库",
            "description": "汇集政务办事指南、公共服务事项、城市运行制度和应急处置资料，供工作人员快速检索与答疑。",
            "state": 4,
            "create_time": 1718000300,
            "update_time": 1718000300,
        },
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

    # Seed completed files and recent tasks for both detail-page tabs.
    now = int(time.time())
    _DOCUMENTS_BY_KB["aidp-kb-faq"] = [
        {
            "file_uuid": "00000000-0000-4000-8000-000000000001",
            "file_ino_no": 1001,
            "file_name": "常见问题汇总.txt",
            "file_size": 2048,
            "file_type": "txt",
            "create_time": 1718000400,
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000002",
            "file_ino_no": 1002,
            "file_name": "troubleshooting.md",
            "file_size": 4096,
            "file_type": "md",
            "create_time": 1718000500,
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000003",
            "file_ino_no": 1003,
            "file_name": "向量入库失败示例.docx",
            "file_size": 3072,
            "file_type": "docx",
            "first_upload_time": now - 3600,
            "update_time": now - 1800,
            "status": 3,
            "error_code": "VEC101",
            "extraction_failure_reason": "向量服务暂时不可用，任务未能完成向量入库。",
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000004",
            "file_ino_no": 1004,
            "file_name": "排队中的制度说明.pdf",
            "file_size": 5120,
            "file_type": "pdf",
            "first_upload_time": now - 900,
            "update_time": now - 600,
            "status": 4,
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000005",
            "file_ino_no": 1005,
            "file_name": "图谱入库失败示例.pdf",
            "file_size": 8192,
            "file_type": "pdf",
            "first_upload_time": now - 7200,
            "update_time": now - 5400,
            "status": 5,
            "error_code": "GRAPH201",
            "extraction_failure_reason": "图谱任务处理失败，请检查知识图谱配置后重试。",
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000006",
            "file_ino_no": 1006,
            "file_name": "正在提取的服务手册.txt",
            "file_size": 4096,
            "file_type": "txt",
            "first_upload_time": now - 300,
            "update_time": now - 120,
            "status": 2,
        },
    ]
    _KNOWLEDGE_BASES["aidp-kb-faq"].update({
        "embedding_model": "bge-m3",
        "vlm_model": "Qwen3-VL-8B-Instruct",
        "rerank_model": "bge-reranker-v2-m3",
        "chunk_mode": 0,
        "chunk_token_num": 512,
        "chunk_overlap_num": 10,
        "topk": 10,
        "similarity": 0.6,
        "is_exist_graph": True,
        "llm_model_name": "Qwen3-8B-Instruct",
        "graph_config": {
            "domain": "general",
            "retrieve_default_topk": 10,
            "retrieve_subgraph_hop": 2,
            "no_think_mode": True,
            "prompt_language": "chinese",
            "prompt_text": "作为专业知识图谱构建引擎，仅提取文本实体、关系、属性三元组，输出固定 JSON 数组。",
            "synonym_merge_enable": False,
            "disambiguation_enable": False,
        },
    })


def _save_state() -> None:
    """Atomically persist _KNOWLEDGE_BASES and _DOCUMENTS_BY_KB to disk.

    Writes to a temporary file and then renames it into place, so a crash
    mid-write cannot corrupt the existing state file. Silently no-ops the
    documents/chunky side of a KB when its document list is missing — only
    KB + document metadata are serialized, not file upload payloads.
    """
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "knowledge_bases": _KNOWLEDGE_BASES,
        "documents_by_kb": _DOCUMENTS_BY_KB,
    }
    tmp_path = _STATE_FILE.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_path, _STATE_FILE)
    except OSError as exc:
        logger.warning("STATE SAVE FAILED  %s: %s", _STATE_FILE, exc)


def _load_state() -> None:
    """Hydrate runtime state from the persisted JSON file, or seed it fresh.

    On the very first run (no file present) populates seed data and writes
    it out so the next restart sees the same 25 KBs. If the file exists but
    is unreadable or not valid JSON, logs a warning and falls back to seeds
    — this keeps the mock usable after accidental file corruption.
    """
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            kb_data = payload.get("knowledge_bases", {})
            doc_data = payload.get("documents_by_kb", {})
            if not isinstance(kb_data, dict) or not isinstance(doc_data, dict):
                raise ValueError("state file payload is not {dict, dict}")
            _KNOWLEDGE_BASES.update(kb_data)
            _DOCUMENTS_BY_KB.update(doc_data)
            for kb in _KNOWLEDGE_BASES.values():
                if isinstance(kb, dict):
                    kb.pop("sensitive_intercept_enalbe", None)
            logger.info(
                "STATE LOAD  restored %d KBs from %s",
                len(_KNOWLEDGE_BASES), _STATE_FILE,
            )
            return
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning(
                "STATE LOAD FAILED  %s unreadable (%s); falling back to seeds",
                _STATE_FILE, exc,
            )

    _seed_initial_data()
    _save_state()
    logger.info(
        "STATE INIT  seeded %d KBs -> %s", len(_KNOWLEDGE_BASES), _STATE_FILE,
    )


def _ensure_document_uuids() -> None:
    """Backfill stable UUIDs for state created before UUID support existed."""
    for kds_id, documents in _DOCUMENTS_BY_KB.items():
        if not isinstance(documents, list):
            continue
        for document in documents:
            if not isinstance(document, dict) or document.get("file_uuid"):
                continue
            file_ino_no = str(document.get("file_ino_no") or uuid.uuid4())
            document["file_uuid"] = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"mock-aidp:{kds_id}:{file_ino_no}")
            )


_load_state()


def _ensure_detail_demo_tasks() -> None:
    """Retain the legacy opt-in task fixture for existing local test workflows."""
    if os.environ.get("AIDP_MOCK_ENABLE_DETAIL_FIXTURES") != "1":
        return
    kds_id = "aidp-kb-faq"
    if kds_id not in _KNOWLEDGE_BASES:
        return
    docs = _DOCUMENTS_BY_KB.setdefault(kds_id, [])
    known_uuids = {str(doc.get("file_uuid")) for doc in docs if doc.get("file_uuid")}
    now = int(time.time())
    fixtures = [
        {
            "file_uuid": "00000000-0000-4000-8000-000000000003",
            "file_ino_no": 1003,
            "file_name": "向量入库失败示例.docx",
            "file_size": 3072,
            "file_type": "docx",
            "first_upload_time": now - 3600,
            "update_time": now - 1800,
            "status": 3,
            "error_code": "VEC101",
            "extraction_failure_reason": "向量服务暂时不可用，任务未能完成向量入库。",
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000004",
            "file_ino_no": 1004,
            "file_name": "排队中的制度说明.pdf",
            "file_size": 5120,
            "file_type": "pdf",
            "first_upload_time": now - 900,
            "update_time": now - 600,
            "status": 4,
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000005",
            "file_ino_no": 1005,
            "file_name": "图谱入库失败示例.pdf",
            "file_size": 8192,
            "file_type": "pdf",
            "first_upload_time": now - 7200,
            "update_time": now - 5400,
            "status": 5,
            "error_code": "GRAPH201",
            "extraction_failure_reason": "图谱任务处理失败，请检查知识图谱配置后重试。",
        },
        {
            "file_uuid": "00000000-0000-4000-8000-000000000006",
            "file_ino_no": 1006,
            "file_name": "正在提取的服务手册.txt",
            "file_size": 4096,
            "file_type": "txt",
            "first_upload_time": now - 300,
            "update_time": now - 120,
            "status": 2,
        },
    ]
    additions = [fixture for fixture in fixtures if fixture["file_uuid"] not in known_uuids]
    if additions:
        docs.extend(additions)
        logger.info("DETAIL FIXTURES  added %d sample upload tasks to %s", len(additions), kds_id)
        _save_state()


def _ensure_chinese_demo_data() -> None:
    """Keep one persisted AIDP sample fully populated for Chinese UI review."""
    kds_id = "aidp-kb-faq"
    kb = _KNOWLEDGE_BASES.get(kds_id)
    if kb is None:
        return

    now = int(time.time())
    name = "政务服务与城市治理知识库"
    description = "汇集政务办事指南、公共服务事项、城市运行制度和应急处置资料，供工作人员快速检索与答疑。"
    if not kb.get("kds_name") or kb.get("kds_name") == "AIDP FAQ":
        kb["kds_name"] = name
    if not kb.get("description") or kb.get("description") == "Frequently asked questions and troubleshooting notes.":
        kb["description"] = description

    defaults = {
        "state": 4,
        "create_time": now - 45 * 24 * 60 * 60,
        "update_time": now - 24 * 60 * 60,
        "created_by": "王晓明",
        "user_name": "王晓明",
        "is_private": 0,
        "current_cap": 0.84,
        "document_count": 8,
        "chunk_count": 286,
        "embedding_model": "bge-m3",
        "is_multimodal": True,
        "caption_enable": 1,
        "vlm_model": "Qwen3-VL-8B-Instruct",
        "rerank_model": "bge-reranker-v2-m3",
        "chunk_mode": 0,
        "chunk_token_num": 1024,
        "chunk_overlap_num": 128,
        "topk": 10,
        "similarity": 0.62,
        "is_exist_graph": True,
        "llm_model_name": "Qwen3-8B-Instruct",
    }
    if kb.get("create_time") == 1718000300:
        kb["create_time"] = now - 45 * 24 * 60 * 60
    if kb.get("update_time") == 1718000300:
        kb["update_time"] = now - 24 * 60 * 60
    for key, value in defaults.items():
        current = kb.get(key)
        if current is None or (isinstance(current, str) and not current.strip()):
            kb[key] = value

    graph_defaults = {
        "domain": "general",
        "retrieve_default_topk": 10,
        "retrieve_subgraph_hop": 2,
        "no_think_mode": False,
        "prompt_language": "chinese",
        "prompt_text": (
            "你是政务服务与城市治理领域的知识图谱构建助手。请从材料中识别办事事项、办理部门、"
            "申请条件、所需材料、办理流程、办理时限、服务地点、政策依据、城市设施、责任单位和应急事件。"
            "仅根据原文建立准确的实体与关系；实体名称保持原文，合并明确指向同一对象的别名，"
            "对简称或同名实体结合上下文消歧。不要补充材料中没有的信息，按接口要求输出结构化 JSON。"
        ),
        "synonym_merge_enable": True,
        "disambiguation_enable": True,
    }
    graph_config = kb.get("graph_config")
    if isinstance(graph_config, str):
        try:
            graph_config = json.loads(graph_config)
        except json.JSONDecodeError:
            graph_config = {}
    if not isinstance(graph_config, dict):
        graph_config = {}
    for key, value in graph_defaults.items():
        current = graph_config.get(key)
        if current is None or (isinstance(current, str) and not current.strip()):
            graph_config[key] = value
    kb["graph_config"] = graph_config

    def demo_file(
        number: int,
        file_name: str,
        file_type: str,
        file_size: int,
        days_ago: int,
        status: int,
        *,
        hours_since_update: int = 2,
        error_code: str | None = None,
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        uploaded_at = now - days_ago * 24 * 60 * 60
        updated_at = now - hours_since_update * 60 * 60
        item: dict[str, Any] = {
            "file_uuid": f"00000000-0000-4000-8000-{number:012d}",
            "file_ino_no": 1000 + number,
            "file_name": file_name,
            "file_size": file_size,
            "file_type": file_type,
            "import_mode": "本地上传",
            "first_upload_time": uploaded_at,
            "update_time": updated_at,
            "status": status,
        }
        if error_code:
            item["error_code"] = error_code
        if failure_reason:
            item["extraction_failure_reason"] = failure_reason
            item["reason"] = failure_reason
        return item

    vector_failure = (
        "文档解析和分片已完成，但向量索引服务暂时不可用，未能写入向量库。请稍后重新提取。"
    )
    graph_failure = (
        "文件已完成向量化，但实体关系抽取未能完成，图谱数据没有写入。请检查知识图谱配置后重试。"
    )
    fixtures = [
        demo_file(1, "政务服务办事指南.pdf", "pdf", 1_835_008, 18, 1, hours_since_update=24),
        demo_file(2, "城市运行管理制度汇编.docx", "docx", 3_276_800, 16, 1, hours_since_update=12),
        demo_file(
            3, "公共服务目录更新.docx", "docx", 482_304, 2, 3,
            hours_since_update=1, error_code="VEC101", failure_reason=vector_failure,
        ),
        demo_file(4, "新市民服务政策手册.pdf", "pdf", 2_146_304, 0, 4, hours_since_update=0),
        demo_file(
            5, "城市设施关联关系数据.xlsx", "xlsx", 786_432, 1, 5,
            hours_since_update=3, error_code="GRAPH201", failure_reason=graph_failure,
        ),
        demo_file(6, "医保异地办理流程说明.txt", "txt", 36_864, 0, 2, hours_since_update=0),
        demo_file(7, "公共服务事项清单.xlsx", "xlsx", 917_504, 14, 1, hours_since_update=48),
        demo_file(8, "12345热线常见问题与答复.md", "md", 58_368, 12, 1, hours_since_update=30),
        demo_file(9, "基层治理工作周报.csv", "csv", 393_216, 10, 1, hours_since_update=20),
        demo_file(10, "应急预案与值班流程.pptx", "pptx", 6_815_744, 8, 1, hours_since_update=16),
        demo_file(11, "市民服务大厅导览.png", "png", 2_752_512, 6, 1, hours_since_update=8),
        demo_file(12, "城市运行平台使用说明.txt", "txt", 44_032, 4, 1, hours_since_update=4),
    ]

    documents = _DOCUMENTS_BY_KB.setdefault(kds_id, [])
    documents_by_uuid = {
        str(document.get("file_uuid")): document
        for document in documents
        if isinstance(document, dict) and document.get("file_uuid")
    }
    legacy_names = {
        "00000000-0000-4000-8000-000000000001": {"常见问题汇总.txt"},
        "00000000-0000-4000-8000-000000000002": {"troubleshooting.md"},
        "00000000-0000-4000-8000-000000000003": {"向量入库失败示例.docx"},
        "00000000-0000-4000-8000-000000000004": {"排队中的制度说明.pdf"},
        "00000000-0000-4000-8000-000000000005": {"图谱入库失败示例.pdf"},
        "00000000-0000-4000-8000-000000000006": {"正在提取的服务手册.txt"},
    }
    for fixture in fixtures:
        existing = documents_by_uuid.get(fixture["file_uuid"])
        if existing is None:
            documents.append(fixture)
            documents_by_uuid[fixture["file_uuid"]] = fixture
        else:
            if not existing.get("file_name") or existing.get("file_name") in legacy_names.get(
                fixture["file_uuid"], set()
            ):
                existing["file_name"] = fixture["file_name"]
            if existing.get("status") is None or existing.get("status") == "":
                existing["status"] = fixture["status"]
            raw_status = str(existing.get("status", "")).strip().upper()
            status_aliases = {
                "COMPLETED": "1",
                "SUCCESS": "1",
                "PROCESSING": "2",
                "EXTRACTING": "2",
                "FAILED": "3",
                "VECTOR_INGESTION_FAILED": "3",
                "UPLOADING": "4",
                "QUEUED": "4",
                "GRAPH_INGESTION_FAILED": "5",
            }
            status_matches_fixture = (
                status_aliases.get(raw_status, raw_status) == str(fixture["status"])
            )
            for key, value in fixture.items():
                if key in {"file_name", "status"}:
                    continue
                if key in {"error_code", "extraction_failure_reason", "reason"}:
                    if status_matches_fixture and not existing.get(key):
                        existing[key] = value
                    continue
                current = existing.get(key)
                if current is None or (isinstance(current, str) and not current.strip()):
                    existing[key] = value

    logger.info(
        "DEMO FIXTURE  ensured Chinese knowledge base %s with %d files",
        kds_id,
        len(documents),
    )
    _save_state()


_ensure_detail_demo_tasks()
_ensure_chinese_demo_data()
_ensure_document_uuids()
_save_state()


def _public_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return document metadata without any mock-only private fields."""
    return {key: value for key, value in document.items() if not key.startswith("_")}


def _find_document(kds_id: str, file_uuid: str) -> Optional[Dict[str, Any]]:
    return next(
        (
            document
            for document in _DOCUMENTS_BY_KB.get(kds_id, [])
            if document.get("file_uuid") == file_uuid
        ),
        None,
    )


def _document_content(document: Dict[str, Any]) -> bytes:
    """Build deterministic mock content for a document download."""
    return (
        f"Mock AIDP content for {document.get('file_name', 'download')}\n"
    ).encode("utf-8")


def _content_disposition(filename: str) -> str:
    """Build a standard ASCII fallback plus RFC 5987 UTF-8 filename header."""
    ascii_name = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\"} else "_"
        for char in filename
    )
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


# =============================================================================
# Document status helpers
# =============================================================================
def _channel_src_dir(kds_id: str) -> str:
    """Return the source directory of a knowledge base's ingestion channel."""
    return f"{_CHANNEL_ROOT}/{kds_id}"


def _kds_id_from_dir_path(dir_path: Optional[str]) -> Optional[str]:
    """Accept the source path and the confirmed AIDP request path ``/{kds_id}``."""
    if not isinstance(dir_path, str):
        return None
    normalized = dir_path.strip("/")
    if normalized in _KNOWLEDGE_BASES:
        return normalized
    prefix = f"{_CHANNEL_ROOT}/"
    if not dir_path.startswith(prefix):
        return None
    return dir_path[len(prefix):].strip("/") or None


def _doc_effective_status(doc: Dict[str, Any]) -> int | str:
    """Return the document's current status, advancing the processing timer.

    AIDP's recent status contract uses numeric strings: 1 success, 2 extracting,
    3 vector-ingestion failure, 4 queued, and 5 graph-ingestion failure.
    Documents persisted before status simulation existed are treated as success.
    """
    status = doc.get("status")
    if status is None or status == "":
        return 1
    if status == STATUS_PROCESSING:
        deadline = doc.get("processing_until")
        if isinstance(deadline, (int, float)) and time.time() < deadline:
            return 2
        return 1

    normalized = str(status).strip().upper()
    aliases = {
        "COMPLETED": 1,
        "SUCCESS": 1,
        "PROCESSING": 2,
        "EXTRACTING": 2,
        "FAILED": 3,
        "VECTOR_INGESTION_FAILED": 3,
        "UPLOADING": 4,
        "QUEUED": 4,
        "GRAPH_INGESTION_FAILED": 5,
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized.isdigit():
        return int(normalized)
    return normalized


def _visible_in_completed_listing(doc: Dict[str, Any]) -> bool:
    """Whether a document appears in the legacy completed-files listing.

    Real AIDP only exposes ingested files there; files still being processed are
    invisible, which is exactly the behaviour the history endpoint replaces.
    """
    return _doc_effective_status(doc) == 1


def _document_timestamp(document: Dict[str, Any]) -> float | None:
    """Return the best available upload timestamp in epoch seconds."""
    value = (
        document.get("first_upload_time")
        or document.get("create_time")
        or document.get("created_at")
        or document.get("update_time")
        or document.get("updated_at")
    )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return None
    return None


# =============================================================================
# Request Models
# =============================================================================
class CreateKbBody(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    embedding_model: Optional[str] = None
    is_multimodal: Optional[bool] = None
    vision_model: Optional[str] = None
    chunk_token_num: int = 1024
    chunk_overlap_num: int = 128
    chunk_mode: int = 0
    is_personal: int = 0
    topk: int = 10
    similarity: float = 0.6
    caption_enable: int = 0
    vlm_model: str = ""
    is_exist_graph: bool = False
    graph_config: Optional[str] = None


def _graph_template(language: str) -> Dict[str, Any]:
    """Use the captured Chinese response; English templates remain synthetic fixtures."""
    if language == "chinese":
        fixture = Path(__file__).with_name("graph_config_template_chinese.json")
        return json.loads(fixture.read_text(encoding="utf-8"))
    english = True
    prompts = {
        domain: (f"Extract entity relationship triples for the {domain} domain."
                 if english else f"你是{domain}领域的信息抽取专家，请抽取明确的实体及其关系三元组。")
        for domain in ("医疗", "金融", "常规", "法律法规")
    }
    entries = [
        ("retrieve_subgraph_hop", "子图扩展跳数", "2", "^[1-3]$", True),
        ("no_think_mode", "禁用LLM思考过程", "是", "^(是|否)$", True),
        ("prompt_language", "提示词语言", "英文" if english else "中文", "^(中文|英文)$", False),
        ("domain", "领域类型", "常规", "^(医疗|金融|常规|法律法规)$", False),
        ("prompt_text", "知识抽取提示词", prompts["常规"], r"^[\s\S]{1,4096}$", False),
        ("synonym_merge_enable", "同义词检测开关", "否", "^(是|否)$", True),
        ("disambiguation_enable", "实体消歧开关", "否", "^(是|否)$", True),
    ]
    value = [dict(param_key=key, param_name=name, param_value=default,
                  regexp=regexp, is_modifiable=modifiable, param_desc=name)
             for key, name, default, regexp, modifiable in entries]
    value[4]["template"] = prompts
    return {"value": value}


def _validate_graph_request(body: CreateKbBody) -> None:
    if not body.is_exist_graph:
        return
    try:
        config = json.loads(body.graph_config or "")
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "graph_config must be a JSON string") from exc
    parameters = _graph_template("chinese")["value"]
    allowed = {p["param_key"] for p in parameters} | {"llm_model_name"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise HTTPException(400, "Unrecognized graph configuration parameter")
    for parameter in parameters:
        value = config.get(parameter["param_key"])
        if not isinstance(value, str) or re.fullmatch(parameter["regexp"], value) is None:
            raise HTTPException(400, f"Invalid graph parameter: {parameter['param_key']}")
    if "llm_model_name" in config and not isinstance(config["llm_model_name"], str):
        raise HTTPException(400, "Invalid llm_model_name")


class UpdateKbBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    chunk_mode: Optional[int] = None
    topk: Optional[int] = None


class DocHistoryBody(BaseModel):
    """Body of POST .../KnowledgeFiles/History (channel + directory scoped)."""

    fs_id: Optional[str] = None
    dir_path: Optional[str] = None
    page: int = 1
    page_size: Optional[int] = Field(default=None, ge=1, le=100)
    status: Optional[int] = Field(default=None, ge=0, le=5)
    keyword: Optional[str] = Field(default=None, max_length=200)


class RetryDocumentsBody(BaseModel):
    file_uuids: List[str] = Field(..., min_length=1)


class DocStatusBody(BaseModel):
    """Body of POST /_mock/doc-status (test control over one document)."""

    kds_id: str
    file_ino_no: str
    status: Literal[
        "UPLOADING", "PROCESSING", "EXTRACTING", "COMPLETED", "FAILED"
    ] = "FAILED"


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


class RemoveFilesBody(BaseModel):
    file_uuids: List[uuid.UUID] = Field(..., min_length=1)


class DownloadFileBody(BaseModel):
    file_uuid: uuid.UUID = Field(...)


# =============================================================================
# Auth helper
# =============================================================================
def _check_auth(authorization: Optional[str]) -> None:
    """Validate Bearer token against the expected API key."""
    expected = f"Bearer {EXPECTED_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


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
    fail with the given status code. Returns 200 with the current plan."""
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


@app.post("/_mock/upload-seconds")
def set_upload_seconds(
    seconds: float = Query(10.0, ge=0.0, le=600.0, description="Upload response delay in seconds"),
) -> JSONResponse:
    """Delay each batch once without blocking other mock requests."""
    global _UPLOAD_SECONDS
    _UPLOAD_SECONDS = seconds
    logger.info("MOCK CONFIG  upload response delay = %s", seconds)
    return JSONResponse(content={"upload_seconds": _UPLOAD_SECONDS})


@app.post("/_mock/processing-seconds")
def set_processing_seconds(
    seconds: float = Query(8.0, ge=0.0, le=600.0, description="Seconds a new upload stays PROCESSING"),
) -> JSONResponse:
    """Tune how long newly uploaded documents stay PROCESSING.

    Set 0 to make uploads complete immediately, or a large value to keep the
    frontend's status polling running while you inspect it.
    """
    global _PROCESSING_SECONDS
    _PROCESSING_SECONDS = seconds
    logger.info("MOCK CONFIG  processing seconds = %s", seconds)
    return JSONResponse(content={"processing_seconds": _PROCESSING_SECONDS})


@app.post("/_mock/history-page-size")
def set_history_page_size(
    size: int = Query(10, ge=1, le=1000, description="Entries returned per history page"),
) -> JSONResponse:
    """Tune how many entries one history page returns.

    Set it to 1 to make every file land on its own page, which is how the
    multi-page walk is exercised locally.
    """
    global _HISTORY_PAGE_SIZE
    _HISTORY_PAGE_SIZE = size
    logger.info("MOCK CONFIG  history page size = %s", size)
    return JSONResponse(content={"history_page_size": _HISTORY_PAGE_SIZE})


@app.post("/_mock/doc-status")
def force_doc_status(body: DocStatusBody) -> JSONResponse:
    """Force one document into a given status (used to render a stage in the UI)."""
    docs = _DOCUMENTS_BY_KB.get(body.kds_id, [])
    for doc in docs:
        # Compare as strings: document ids are numeric in some state files and
        # strings in others, and callers should not have to care.
        if str(doc.get("file_ino_no")) == str(body.file_ino_no):
            doc["status"] = body.status
            doc.pop("processing_until", None)
            _save_state()
            logger.info(
                "MOCK CONFIG  kds_id=%s file=%s status=%s",
                body.kds_id, body.file_ino_no, body.status,
            )
            return JSONResponse(content={"doc": {**doc, "status": body.status}})

    raise HTTPException(
        status_code=404,
        detail=f"Document {body.file_ino_no} not found in {body.kds_id}",
    )


# =============================================================================
# Knowledge Base CRUD
# =============================================================================


@app.get(_KB_PREFIX)
def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """List knowledge bases with pagination + next_link (matches AIDP shape).

    ``keyword`` narrows the set by knowledge-base name (case-insensitive), the
    way the real AIDP list endpoint does. Without this the mock returned every
    KB for a filtered request, which made the search feature look broken in
    local runs once the page stopped filtering client-side.
    """
    _check_auth(authorization)

    all_items = list(_KNOWLEDGE_BASES.values())
    normalized_keyword = (keyword or "").strip().lower()
    if normalized_keyword:
        all_items = [
            kb
            for kb in all_items
            if normalized_keyword in str(kb.get("kds_name") or "").lower()
        ]
    start = (page - 1) * page_size
    end = start + page_size
    # Enrich each item with document_count (same as detail endpoint does)
    enriched = [{
        **kb,
        "document_count": sum(
            1 for doc in _DOCUMENTS_BY_KB.get(kb["kds_id"], [])
            if _visible_in_completed_listing(doc)
        ),
    } for kb in all_items]
    items = enriched[start:end]

    next_link = None
    if end < len(all_items):
        next_link = f"{_KB_PREFIX}?page={page + 1}&page_size={page_size}"

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
    # Only ingested files count on the legacy endpoint, matching the list.
    count = len([
        doc for doc in _DOCUMENTS_BY_KB.get(kds_id, [])
        if _visible_in_completed_listing(doc)
    ])
    logger.info("COUNT DOCS  kds_id=%s count=%d", kds_id, count)
    return JSONResponse(content={"count": count})


@app.put(_KB_PREFIX)
def create_knowledge_base(
    body: CreateKbBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Create a new knowledge base. AIDP uses PUT on the collection endpoint."""
    _check_auth(authorization)
    _validate_graph_request(body)

    kds_id = f"aidp-kb-{uuid.uuid4().hex[:8]}"
    now = int(time.time())
    new_kb = {
        **body.model_dump(exclude_none=True),
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
    _save_state()
    return JSONResponse(content=new_kb)


@app.get(f"{_KB_PREFIX}/GraphConfigTemplate")
def graph_config_template(
    language: str = Query("chinese", pattern="^(chinese|english)$"),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    return JSONResponse(content=_graph_template(language))


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
    result = {
        **kb,
        "document_count": sum(1 for doc in docs if _visible_in_completed_listing(doc)),
    }

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
    if body.chunk_mode is not None:
        kb["chunk_mode"] = body.chunk_mode
    if body.topk is not None:
        kb["topk"] = body.topk
    kb["update_time"] = int(time.time())

    logger.info("UPDATE  kds_id=%s name=%r description=%r", kds_id, body.name, body.description)
    _save_state()
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
    _save_state()
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

    if _UPLOAD_SECONDS > 0:
        await asyncio.sleep(_UPLOAD_SECONDS)

    success_docs: List[Dict[str, Any]] = []
    failed: List[Dict[str, str]] = []
    for f in files:
        try:
            content = await f.read()
            file_ino_no = max(
                (
                    document["file_ino_no"]
                    for document in _DOCUMENTS_BY_KB.get(kds_id, [])
                    if isinstance(document.get("file_ino_no"), int)
                ),
                default=0,
            ) + 1
            doc = {
                "file_uuid": str(uuid.uuid4()),
                "file_ino_no": file_ino_no,
                "file_name": f.filename or "unknown",
                "file_size": len(content),
                "file_type": (f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else "bin"),
                "create_time": int(time.time()),
                # Uploaded files enter the ingestion pipeline immediately: the
                # legacy list endpoint hides them until the timer elapses, while
                # the history endpoint reports them as PROCESSING.
                "status": STATUS_PROCESSING,
                "processing_until": time.time() + _PROCESSING_SECONDS,
            }
            _DOCUMENTS_BY_KB.setdefault(kds_id, []).append(doc)
            success_docs.append(doc)
            logger.info("UPLOAD  kds_id=%s file=%s size=%d", kds_id, f.filename, len(content))
        except Exception as e:
            failed.append({
                "file_name": f.filename or "unknown",
                "reason_zh": f"文件上传失败：{e}",
                "reason_en": f"File upload failed: {e}",
            })
            logger.warning("UPLOAD FAIL  kds_id=%s file=%s error=%s", kds_id, f.filename, e)

    _save_state()
    return JSONResponse(content={
        "summary": {
            "total": len(files),
            "success": len(success_docs),
            "failed": len(failed),
        },
        "success_list": [
            {
                "file_name": doc["file_name"],
                "file_type": doc["file_type"],
                "file_size": doc["file_size"],
                "file_ino_no": doc["file_ino_no"],
                "file_uuid": doc["file_uuid"],
                "first_upload_time": doc["create_time"],
            }
            for doc in success_docs
        ],
        "failed_list": failed,
    })


@app.get(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles")
def list_documents(
    kds_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: Optional[str] = Query(default=None, max_length=200),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """List documents in a knowledge base with pagination.

    Only ingested (COMPLETED) files are returned: real AIDP hides files that are
    still being chunked/embedded here, which is why the frontend used to show
    nothing right after an upload.
    """
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    all_docs = [
        doc for doc in _DOCUMENTS_BY_KB.get(kds_id, [])
        if _visible_in_completed_listing(doc)
    ]
    normalized_keyword = keyword.strip().casefold() if isinstance(keyword, str) else ""
    if normalized_keyword:
        all_docs = [
            doc for doc in all_docs
            if normalized_keyword in str(doc.get("file_name") or "").casefold()
        ]
    start = (page - 1) * page_size
    end = start + page_size
    items = [_public_document(doc) for doc in all_docs[start:end]]

    # Real AIDP returns `next_link` as the authoritative "more pages exist"
    # signal. When there are no more docs, next_link is simply absent.
    # `total_count` mirrors AIDP's page count; next_link signals another page.
    next_link = None
    if end < len(all_docs):
        next_link = f"{_KB_PREFIX}/{kds_id}/KnowledgeFiles?page={page + 1}&page_size={page_size}"
        if normalized_keyword:
            next_link += f"&keyword={quote(keyword.strip(), safe='')}"

    logger.info("LIST DOCS  kds_id=%s page=%d returned=%d total=%d", kds_id, page, len(items), len(all_docs))
    return JSONResponse(content={
        "value": items,
        "total_count": len(items),
        "next_link": next_link,
    })


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Remove")
def remove_documents(
    kds_id: str,
    body: RemoveFilesBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Remove documents by file UUID and return per-file success/failure lists."""
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    documents = _DOCUMENTS_BY_KB.setdefault(kds_id, [])
    remaining = list(documents)
    success_list: List[Dict[str, str]] = []
    failed_list: List[Dict[str, str]] = []
    for raw_file_uuid in body.file_uuids:
        file_uuid = str(raw_file_uuid)
        matched = next(
            (document for document in remaining if document.get("file_uuid") == file_uuid),
            None,
        )
        if matched is None:
            failed_list.append({"file_uuid": file_uuid})
            continue
        remaining.remove(matched)
        success_list.append({"file_uuid": file_uuid})

    _DOCUMENTS_BY_KB[kds_id] = remaining
    _save_state()
    logger.info(
        "REMOVE DOCS  kds_id=%s total=%d success=%d failed=%d",
        kds_id,
        len(body.file_uuids),
        len(success_list),
        len(failed_list),
    )
    return JSONResponse(content={
        "summary": {
            "total": len(body.file_uuids),
            "success": len(success_list),
            "failed": len(failed_list),
        },
        "success_list": success_list,
        "failed_list": failed_list,
    })


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Download")
def download_document(
    kds_id: str,
    body: DownloadFileBody,
    authorization: Optional[str] = Header(default=None),
) -> StreamingResponse:
    """Return deterministic binary content for a document download."""
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    file_uuid = str(body.file_uuid)
    document = _find_document(kds_id, file_uuid)
    if document is None:
        raise HTTPException(status_code=404, detail=f"File {file_uuid} not found")

    filename = str(document.get("file_name") or "download")
    content = _document_content(document)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response_headers = {
        "Content-Disposition": _content_disposition(filename),
        "X-File-Size": str(len(content)),
    }
    async def content_stream():
        for offset in range(0, len(content), 8 * 1024):
            yield content[offset : offset + 8 * 1024]

    return StreamingResponse(
        content_stream(),
        media_type=content_type,
        headers=response_headers,
    )


# =============================================================================
# Ingestion channels + knowledge-file history
# =============================================================================


@app.get(f"{_KB_PREFIX}/{{kds_id}}/Channels")
def list_channels(
    kds_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """List the ingestion channels feeding one knowledge base.

    The catalog is knowledge-base scoped, so a channel exposes the file-system
    id and source directory the history endpoint is addressed with, plus
    ``kds_id`` so a caller can associate the channel with its KB.
    """
    _check_auth(authorization)

    kb = _KNOWLEDGE_BASES.get(kds_id)
    if kb is None:
        logger.info("LIST CHANNELS  unknown kds_id=%s -> 404", kds_id)
        return JSONResponse(
            status_code=404,
            content={"detail": f"Knowledge base {kds_id} not found"},
        )

    items = [
        {
            "fs_id": f"mock-fs-{kds_id}",
            "src_dir": _channel_src_dir(kds_id),
            "kds_id": kds_id,
            "name": kb.get("kds_name"),
        }
    ]
    logger.info("LIST CHANNELS  kds_id=%s returned=%d", kds_id, len(items))
    return JSONResponse(content={"value": items})


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/History")
def knowledge_file_history(
    kds_id: str,
    body: DocHistoryBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Return one filtered page of this channel's recent file history.

    The endpoint is knowledge-base scoped, like the channel catalog and the
    document list; the body still addresses the request to one channel directory
    of that KB. AIDP retains the last 30 days of history, supports status and
    file-name filtering, and includes summary counts independent of the filters.
    """
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        logger.info("FILE HISTORY  unknown kds_id=%s -> 404", kds_id)
        return JSONResponse(
            status_code=404,
            content={"detail": f"Knowledge base {kds_id} not found"},
        )

    if _kds_id_from_dir_path(body.dir_path) != kds_id:
        logger.info(
            "FILE HISTORY  dir_path=%r does not belong to kds_id=%s -> empty",
            body.dir_path,
            kds_id,
        )
        return JSONResponse(content={"value": []})

    cutoff = time.time() - 30 * 24 * 60 * 60
    all_recent_items = [
        {
            **doc,
            "dir_path": _channel_src_dir(kds_id),
            "status": _doc_effective_status(doc),
        }
        for doc in _DOCUMENTS_BY_KB.get(kds_id, [])
        if (_document_timestamp(doc) is not None
            and _document_timestamp(doc) >= cutoff)
    ]
    all_recent_items.sort(key=lambda item: item["status"] in _TERMINAL_STATUSES)
    stats = {
        "total_record_count": len(all_recent_items),
        "success_record_count": sum(1 for item in all_recent_items if item["status"] == 1),
        "processing_record_count": sum(1 for item in all_recent_items if item["status"] == 2),
        "failed_record_count": sum(1 for item in all_recent_items if item["status"] in (3, 5)),
        "queued_record_count": sum(1 for item in all_recent_items if item["status"] == 4),
    }
    items = list(all_recent_items)
    if body.status not in (None, 0):
        status_aliases = {
            1: {1, "1", STATUS_COMPLETED, "SUCCESS"},
            2: {2, "2", "PROCESSING", "EXTRACTING"},
            3: {3, "3", STATUS_FAILED, "VECTOR_INGESTION_FAILED"},
            4: {4, "4", "UPLOADING", "QUEUED"},
            5: {5, "5", "GRAPH_INGESTION_FAILED"},
        }
        accepted = status_aliases.get(body.status, set())
        items = [item for item in items if item["status"] in accepted]
    normalized_keyword = body.keyword.strip().casefold() if isinstance(body.keyword, str) else ""
    if normalized_keyword:
        items = [
            item for item in items
            if normalized_keyword in str(item.get("file_name") or "").casefold()
        ]
    page = body.page if isinstance(body.page, int) and body.page > 0 else 1
    page_size = body.page_size or _HISTORY_PAGE_SIZE
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    next_link = (
        f"{_KB_PREFIX}/{kds_id}/KnowledgeFiles/History?page={page + 1}"
        f"&page_size={page_size}"
        if end < len(items)
        else None
    )
    if next_link and body.status not in (None, 0):
        next_link += f"&status={body.status}"
    if next_link and normalized_keyword:
        next_link += f"&keyword={quote(body.keyword.strip(), safe='')}"
    logger.info(
        "FILE HISTORY  kds_id=%s fs_id=%s dir_path=%s page=%d returned=%d total=%d",
        kds_id, body.fs_id, body.dir_path, page, len(page_items), len(items),
    )
    return JSONResponse(content={
        "value": page_items,
        "total_count": len(items),
        "next_link": next_link,
        **stats,
    })


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Retry")
def retry_documents(
    kds_id: str,
    body: RetryDocumentsBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Queue one or more failed files using the AIDP array request shape."""
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    success_list: list[dict[str, str]] = []
    failed_list: list[dict[str, str]] = []
    retryable = {3, 5, "3", "5", STATUS_FAILED, "VECTOR_INGESTION_FAILED", "GRAPH_INGESTION_FAILED"}
    for file_uuid in dict.fromkeys(body.file_uuids):
        doc = _find_document(kds_id, file_uuid)
        if doc is None or doc.get("status") not in retryable:
            failed_list.append({"file_uuid": file_uuid, "reason": "File is not in a retryable failed state"})
            continue
        doc["status"] = 4
        doc["update_time"] = int(time.time())
        doc.pop("error_code", None)
        doc.pop("extraction_failure_reason", None)
        doc.pop("reason", None)
        success_list.append({"file_uuid": file_uuid})

    _save_state()
    return JSONResponse(content={
        "summary": {
            "total": len(success_list) + len(failed_list),
            "success": len(success_list),
            "failed": len(failed_list),
        },
        "success_list": success_list,
        "failed_list": failed_list,
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
        "model_name": "/models/FileEmbeddingModel_v0_1_1/v1.0.0/FileEmbeddingModel_v0_1_1",
        "display_name": "bge-m3", "model_type": "embedding",
        "application": ["KnowledgeBase", "MemoryBase"], "service": "embedding",
    },
    {
        "api_key": "",
        "application": "All",
        "created_at": 1782716626,
        "max_tokens": 32768,
        "model_name": "model_1",
        "display_name": "Qwen3-8B", "model_type": "llm",
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
        "display_name": "Qwen3-VL-8B-Instruct", "model_type": "vlm",
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
        "display_name": "Qwen3-VL-32B-Instruct", "model_type": "vlm",
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
        "display_name": "InternVL2-26B", "model_type": "vlm",
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
        "display_name": "Document parser", "model_type": "llm",
        "properties": {"description": "Should NOT appear for KnowledgeBase.", "model_type": "external"},
        "service": "llm",
    },
]


@app.get(_MODELS_PREFIX)
def list_models(
    service: str = Query(""),
    app: str = Query("KnowledgeBase"),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Return the list of registered models. Real AIDP does NOT filter by the
    ``app`` query param — callers must post-filter by ``application``. The
    backend (aidp_service._is_kb_applicable) does this, so we just dump the
    raw seed data here.
    """
    _check_auth(authorization)
    models = [m for m in _MOCK_MODELS if not service or m["model_type"] == service]
    logger.info("LIST MODELS  service=%s app=%s returned=%d", service, app, len(models))
    return JSONResponse(content={
        "service": service,
        "models": models,
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
        "upload_seconds": _UPLOAD_SECONDS,
    }


@app.post("/_reset")
def reset_state() -> Dict[str, str]:
    """Reset in-memory state back to seeds (useful between test runs).

    Also deletes the persisted state file so the on-disk record matches the
    in-memory one; otherwise the next restart would resurrect the pre-reset
    data and nullify the effect of ``POST /_reset``.
    """
    _KNOWLEDGE_BASES.clear()
    _DOCUMENTS_BY_KB.clear()
    _seed_initial_data()
    _ensure_detail_demo_tasks()
    _ensure_chinese_demo_data()
    _ensure_document_uuids()
    _save_state()
    logger.info("RESET  state restored to seeds, persisted to %s", _STATE_FILE)
    return {"status": "reset"}


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIDP Management Mock Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=30081, help="Bind port (default: 30081)")
    parser.add_argument("--api-key", default=EXPECTED_API_KEY, help="Expected Bearer API key")
    parser.add_argument("--upload-seconds", type=float, default=10.0, help="Upload response delay (default: 10 seconds)")
    args = parser.parse_args()
    if not 0 <= args.upload_seconds <= 600:
        parser.error("--upload-seconds must be between 0 and 600")

    EXPECTED_API_KEY = args.api_key
    _UPLOAD_SECONDS = args.upload_seconds

    import uvicorn

    print(f"\nAIDP Mock Server starting on http://{args.host}:{args.port}")
    print(f"  Tenant path prefix: {_KB_PREFIX}")
    # Don't print the full credential — secret scanners flag this even for
    # mock/test-only keys. The key is a fixed literal visible in this file's
    # source; operators who need it can read it there.
    print(f"  Expected API key:   Bearer *** (see EXPECTED_API_KEY constant)")
    print(f"  Seed KBs:           {len(_KNOWLEDGE_BASES)} pre-populated")
    print(f"  POST /_reset to restore initial state\n")

    uvicorn.run(app, host=args.host, port=args.port)
