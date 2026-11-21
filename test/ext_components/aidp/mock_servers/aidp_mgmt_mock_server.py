# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Standalone mock AIDP server for Nexent AIDP management endpoint testing.

CLI upload responses are delayed by 10 seconds; use --upload-seconds 0 or
POST /_mock/upload-seconds?seconds=0 for fast uploads.

Simulates the AIDP native API endpoints consumed by backend/services/aidp_service.py:
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases          (list)
  - PUT    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases          (create)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}     (detail)
  - PATCH  /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}     (update)
  - DELETE /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}     (delete)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Folders/{folder_id}     (one level; include_files=true for files)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Folders/{parent_id}     (create folder)
  - PATCH  /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Folders/{folder_id}     (rename folder)
  - DELETE /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Folders/{folder_id}     (delete empty folder)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Folders/{folder_id}/Move (move folder)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Upload  (upload docs; target_folder_path + target_folder_id + directory relative_paths)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles         (list docs)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Move    (move files)
  - PATCH  /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles         (rename file)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Channels               (ingestion channels)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/History (all-status file history)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Remove  (remove docs)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Retry  (retry failed docs)
  - POST   /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/KnowledgeFiles/Download (download doc)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/OcrAnnotate/{file_uuid}  (preview doc)
  - POST   /KnowledgeBase/Tenants/{tenant}/Retrieval/FusionSearch  (search - preserved from reference)

Document status simulation (drives the "processing status" UI):
  * Uploads are immediately visible in the completed-files list by default, so
    a successful upload followed by the drawer's one-time refresh has an
    observable result. Set ``_PROCESSING_SECONDS`` above zero with
    ``POST /_mock/processing-seconds?seconds=N`` to simulate asynchronous
    ingestion and exercise processing-status polling.
  * ``POST /_mock/doc-status`` (body ``{kds_id, file_ino_no, status}``) forces one
    document into any status without waiting for the timer, including the
    non-terminal ``UPLOADING`` / ``EXTRACTING`` stages.
  * ``GET .../KnowledgeFiles`` keeps returning COMPLETED documents only (mirrors
    real AIDP), while ``POST .../KnowledgeFiles/History`` returns every status.
  * ``POST .../KnowledgeFiles/History`` returns records from the last 30 days
    and supports page, page_size, file-name keyword, and numeric status filters.
    Tune the default page size with ``POST /_mock/history-page-size?size=N``.
  * ``GET .../OcrAnnotate/{file_uuid}`` serves docx/xlsx/pptx/pdf/txt unchanged
    and answers every other format with a synthetic PDF - which is what real AIDP
    does - reporting the name it served in the ``X-File-Name`` header, so a
    converted document no longer carries its uploaded extension.

Knowledge base + document state is persisted to ``_state/knowledge_bases.json``
(next to this file). On restart the mock loads the file, so KBs created by
tests or frontend sessions survive across restarts without re-creation
(which was otherwise the cause of spurious 404s in list endpoints against
stale Nexent permission rows). ``POST /_reset`` clears the file and
rebuilds the seed data. On startup, the mock upgrades the existing FAQ
seed to a fully populated Chinese knowledge base with recent file and
upload-task examples without clearing other persisted state. Run with:
    python aidp_mgmt_mock_server.py --port 30081
"""
import argparse
import asyncio
import json
import logging
import mimetypes
import zlib
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from starlette.responses import JSONResponse, Response, StreamingResponse

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

# Retrieval channels accepted in ``search_method``; three channels are always
# expressed as the canonical ``hybrid_search`` value.
_RETRIEVAL_CHANNELS = ("vector_search", "full_text_search", "graph_search")
_KB_PREFIX = f"/KnowledgeBase/Tenants/{TENANT}/KnowledgeBases"
_SW_PREFIX = f"{_KB_PREFIX}/{{kds_id}}/SensitiveWords"
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
# Default to immediate completion so the single file-list refresh on drawer
# close can show a successful upload. Tests can opt into asynchronous ingestion
# through POST /_mock/processing-seconds.
_PROCESSING_SECONDS = 0.0
_UPLOAD_SECONDS = 0.0
_FILE_QUERY_SECONDS = 0.0
_FILE_QUERY_FAIL = False
_FILE_DELETE_FAIL = False
# Real AIDP keeps a deleted row visible with file_status=1 for about five
# seconds before removing it from KnowledgeFiles. History keeps the row as an
# audit record. Tests can override this to zero when they do not need the
# transition window.
_FILE_DELETE_SECONDS = 5.0

# Entries one history page returns. Real AIDP pages the channel directory, so the
# backend has to walk the pages; keep this small to exercise that locally.
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
# Sensitive word dictionaries keyed by knowledge base, then by word ID.
_SENSITIVE_WORDS: Dict[str, Dict[str, Dict[str, Any]]] = {}
# Explicit folders per knowledge base. Documents also carry ``folder_path``;
# a folder exists here even when it is empty, matching AIDP's real Folders API.
# Entries look like ``{"folder_path": "/政策制度", "create_time": 173...}``.
_FOLDERS_BY_KB: Dict[str, List[Dict[str, Any]]] = {}
# Uploaded file payloads keyed by ``file_uuid``.
#
# Real AIDP hands the original file back on download and preview, which is what
# lets the frontend render Office formats itself. Payloads therefore have to
# survive an upload, but they are kept in memory only: ``_save_state`` serializes
# metadata, and a mock restart legitimately loses the bytes it received.
_DOCUMENT_PAYLOADS: dict[str, bytes] = {}

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
            "extraction_failure_reason": json.dumps(
                {"error_code": 1520, "msg": "向量服务暂时不可用，任务未能完成向量入库。"},
                ensure_ascii=False,
            ),
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
            "extraction_failure_reason": json.dumps(
                {"error_code": 1601, "msg": "图谱任务处理失败，请检查知识图谱配置后重试。"},
                ensure_ascii=False,
            ),
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
        {
            "file_uuid": "00000000-0000-4000-8000-000000000007",
            "file_ino_no": 1007,
            "file_name": "删除失败示例.txt",
            "file_size": 1024,
            "file_type": "txt",
            "first_upload_time": now - 7200,
            "update_time": now - 3600,
            "status": 1,
            "file_status": 2,
        },
        {
            # Original file for the seeded image chunk. The image itself is
            # still served by AIDP, while downloads use this file identity.
            "file_uuid": "00000000-0000-4000-8000-000000000008",
            "file_ino_no": 1008,
            "file_name": "肝脏医学影像.jpg",
            "file_size": 65536,
            "file_type": "jpg",
            "create_time": 1718000600,
        },
    ]
    _DOCUMENTS_BY_KB["aidp-kb-product"] = [
        {
            # Both seeded product chunks cite this one original file.
            "file_uuid": "00000000-0000-4000-8000-000000000101",
            "file_ino_no": 1101,
            "file_name": "AIDP产品介绍.pdf",
            "file_size": 4096,
            "file_type": "pdf",
            "create_time": 1718000700,
        },
    ]
    _KNOWLEDGE_BASES["aidp-kb-faq"].update({
        "embedding_model": "/models/FileEmbeddingModel_v0_1_1/v1.0.0/FileEmbeddingModel_v0_1_1",
        "vlm_model": "Qwen3-VL-8B-Instruct",
        "chunk_mode": 0,
        "chunk_token_num": 512,
        "chunk_overlap_num": 10,
        "topk": 10,
        "similarity": 0.6,
        "is_exist_graph": True,
        "llm_model_name": "qwen3_8b",
        "graph_config": {
            "domain": "general",
            "retrieve_subgraph_hop": 2,
            "no_think_mode": True,
            "prompt_language": "chinese",
            "prompt_text": "作为专业知识图谱构建引擎，仅提取文本实体、关系、属性三元组，输出固定 JSON 数组。",
            "synonym_merge_enable": False,
            "disambiguation_enable": False,
            "llm_model_name": "qwen3_8b",
        },
    })
    _seed_sensitive_words_if_empty()


def _seed_sensitive_words_if_empty() -> None:
    """Seed two knowledge bases with distinct dictionaries for isolation tests."""
    if _SENSITIVE_WORDS:
        return
    seeds = {
        "aidp-kb-faq": [
            {
                "id": "sw-faq-builtin-black",
                "word": "涉政",
                "mode": "BLACK",
                "description": "内置禁止词示例，命中后拦截文件入库。",
                "source": "BUILT_IN",
            },
            {
                "id": "sw-faq-builtin-white",
                "word": "示例",
                "mode": "WHITE",
                "description": "内置允许词示例，用于排除误判。",
                "source": "BUILT_IN",
            },
            {
                "id": "sw-faq-black",
                "word": "暴力",
                "mode": "BLACK",
                "description": "自定义禁止词示例。",
                "source": "CUSTOM",
            },
            {
                "id": "sw-faq-white",
                "word": "携带",
                "mode": "WHITE",
                "description": "自定义允许词示例。",
                "source": "CUSTOM",
            },
            {
                "id": "sw-faq-white-2",
                "word": "合规",
                "mode": "WHITE",
                "description": "自定义允许词示例：合规表述。",
                "source": "CUSTOM",
            },
        ],
        "aidp-kb-04": [
            {
                "id": "sw-support-builtin-black",
                "word": "诈骗",
                "mode": "BLACK",
                "description": "客服库内置禁止词示例。",
                "source": "BUILT_IN",
            },
            {
                "id": "sw-support-black",
                "word": "退款",
                "mode": "BLACK",
                "description": "客服库禁止词示例。",
                "source": "CUSTOM",
            },
            {
                "id": "sw-support-black-2",
                "word": "保证收益",
                "mode": "BLACK",
                "description": "客服库禁止词示例：承诺收益。",
                "source": "CUSTOM",
            },
            {
                "id": "sw-support-white",
                "word": "优惠",
                "mode": "WHITE",
                "description": "客服库允许词示例。",
                "source": "CUSTOM",
            },
            {
                "id": "sw-support-white-2",
                "word": "合同",
                "mode": "WHITE",
                "description": "客服库允许词示例：合同条款。",
                "source": "CUSTOM",
            },
        ],
    }
    for kds_id, words in seeds.items():
        _SENSITIVE_WORDS[kds_id] = {item["id"]: dict(item) for item in words}


def _save_state() -> None:
    """Atomically persist KB, document and sensitive-word state to disk.

    Writes to a temporary file and then renames it into place, so a crash
    mid-write cannot corrupt the existing state file. Silently no-ops the
    documents/chunky side of a KB when its document list is missing — only
    KB + document metadata are serialized, not file upload payloads.
    """
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "knowledge_bases": _KNOWLEDGE_BASES,
        "documents_by_kb": _DOCUMENTS_BY_KB,
        "sensitive_words_by_kb": _SENSITIVE_WORDS,
        "folders_by_kb": _FOLDERS_BY_KB,
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
            word_data = payload.get("sensitive_words_by_kb", {})
            folder_data = payload.get("folders_by_kb", {})
            if not isinstance(kb_data, dict) or not isinstance(doc_data, dict):
                raise ValueError("state file payload is not {dict, dict}")
            _KNOWLEDGE_BASES.update(kb_data)
            _DOCUMENTS_BY_KB.update(doc_data)
            if isinstance(word_data, dict):
                _SENSITIVE_WORDS.update(word_data)
            if isinstance(folder_data, dict):
                _FOLDERS_BY_KB.update(folder_data)
            for kb in _KNOWLEDGE_BASES.values():
                if isinstance(kb, dict):
                    kb.pop("sensitive_intercept_enalbe", None)
            _seed_sensitive_words_if_empty()
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


def _ensure_source_identity_documents() -> None:
    """Keep download fixtures for retrieval chunks in already persisted state.

    FusionSearch chunks carry ``metadata.file_uuid`` / ``metadata.kds_id``; the
    referenced original files must exist in the same mock knowledge base for
    the download and page-source contracts to be testable after a restart.
    """
    fixtures = {
        "aidp-kb-product": [
            {
                "file_uuid": "00000000-0000-4000-8000-000000000101",
                "file_ino_no": 1101,
                "file_name": "AIDP产品介绍.pdf",
                "file_size": 4096,
                "file_type": "pdf",
                "create_time": 1718000700,
            }
        ],
        "aidp-kb-faq": [
            {
                "file_uuid": "00000000-0000-4000-8000-000000000008",
                "file_ino_no": 1008,
                "file_name": "肝脏医学影像.jpg",
                "file_size": 65536,
                "file_type": "jpg",
                "create_time": 1718000600,
            }
        ],
    }
    changed = False
    for kds_id, candidates in fixtures.items():
        if kds_id not in _KNOWLEDGE_BASES:
            continue
        documents = _DOCUMENTS_BY_KB.setdefault(kds_id, [])
        known = {
            str(document.get("file_uuid"))
            for document in documents
            if isinstance(document, dict) and document.get("file_uuid")
        }
        additions = [
            candidate
            for candidate in candidates
            if candidate["file_uuid"] not in known
        ]
        if additions:
            documents.extend(additions)
            changed = True
    if changed:
        _save_state()
        logger.info("SOURCE IDENTITY  ensured original-file download fixtures")


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
            "extraction_failure_reason": json.dumps(
                {"error_code": 1520, "msg": "向量服务暂时不可用，任务未能完成向量入库。"},
                ensure_ascii=False,
            ),
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
            "extraction_failure_reason": json.dumps(
                {"error_code": 1601, "msg": "图谱任务处理失败，请检查知识图谱配置后重试。"},
                ensure_ascii=False,
            ),
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
        "embedding_model": "/models/FileEmbeddingModel_v0_1_1/v1.0.0/FileEmbeddingModel_v0_1_1",
        "is_multimodal": True,
        "caption_enable": 1,
        "vlm_model": "Qwen3-VL-8B-Instruct",
        "chunk_mode": 0,
        "chunk_token_num": 1024,
        "chunk_overlap_num": 128,
        "topk": 10,
        "similarity": 0.62,
        "is_exist_graph": True,
        "llm_model_name": "qwen3_8b",
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
        "retrieve_subgraph_hop": 2,
        "no_think_mode": False,
        "prompt_language": "chinese",
        "llm_model_name": "qwen3_8b",
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
        if failure_reason:
            item["extraction_failure_reason"] = failure_reason
        return item

    vector_failure = json.dumps(
        {
            "error_code": 1520,
            "msg": "文档解析和分片已完成，但向量索引服务暂时不可用，未能写入向量库。请稍后重新提取。",
        },
        ensure_ascii=False,
    )
    graph_failure = json.dumps(
        {
            "error_code": 1601,
            "msg": "文件已完成向量化，但实体关系抽取未能完成，图谱数据没有写入。请检查知识图谱配置后重试。",
        },
        ensure_ascii=False,
    )
    fixtures = [
        demo_file(1, "政务服务办事指南.pdf", "pdf", 1_835_008, 18, 1, hours_since_update=24),
        demo_file(2, "城市运行管理制度汇编.docx", "docx", 3_276_800, 16, 1, hours_since_update=12),
        demo_file(
            3, "公共服务目录更新.docx", "docx", 482_304, 2, 3,
            hours_since_update=1, failure_reason=vector_failure,
        ),
        demo_file(4, "新市民服务政策手册.pdf", "pdf", 2_146_304, 0, 4, hours_since_update=0),
        demo_file(
            5, "城市设施关联关系数据.xlsx", "xlsx", 786_432, 1, 5,
            hours_since_update=3, failure_reason=graph_failure,
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


# Demo folder layout for the Chinese review knowledge base. Documents keep the
# folder they are assigned to across restarts; folders without documents
# (``/归档``) prove that empty folders are preserved and can be removed.
_DEMO_FOLDERS = (
    "/政策制度",
    "/政策制度/公共服务",
    "/归档",
)
_DEMO_DOCUMENT_FOLDERS = {
    "00000000-0000-4000-8000-000000000001": "/政策制度",
    "00000000-0000-4000-8000-000000000002": "/政策制度",
    "00000000-0000-4000-8000-000000000007": "/政策制度/公共服务",
    "00000000-0000-4000-8000-000000000008": "/政策制度/公共服务",
    "00000000-0000-4000-8000-000000000009": "/",
    "00000000-0000-4000-8000-000000000010": "/",
    "00000000-0000-4000-8000-000000000011": "/",
    "00000000-0000-4000-8000-000000000012": "/",
}


def _ensure_folder_structure() -> None:
    """Seed the demo folder tree and give every existing document a folder.

    Only fills missing values so folders/documents created through the UI (or a
    previous local run) are never overwritten. Other knowledge bases start with
    no folders, which is also a valid AIDP state.
    """
    kds_id = "aidp-kb-faq"
    if kds_id not in _KNOWLEDGE_BASES:
        return
    folders = _FOLDERS_BY_KB.setdefault(kds_id, [])
    if not folders:
        now = int(time.time())
        folders.extend(
            {"folder_path": path, "create_time": now}
            for path in _DEMO_FOLDERS
        )
    for document in _DOCUMENTS_BY_KB.get(kds_id, []):
        if not isinstance(document, dict) or document.get("folder_path"):
            continue
        file_uuid = str(document.get("file_uuid") or "")
        document["folder_path"] = _DEMO_DOCUMENT_FOLDERS.get(file_uuid, "/")


_ensure_detail_demo_tasks()
_ensure_chinese_demo_data()
_ensure_document_uuids()
_ensure_source_identity_documents()
_ensure_folder_structure()
_save_state()


def _public_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return document metadata without any mock-only private fields."""
    return {key: value for key, value in document.items() if not key.startswith("_")}


def _active_documents(kds_id: str) -> List[Dict[str, Any]]:
    """Return completed files still visible in KnowledgeFiles.

    A successful Remove marks the row ``file_status=1`` and keeps it visible
    until ``_deleted_at`` passes; after that the row is hidden here but stays in
    the history audit log.
    """
    now = time.time()
    return [
        doc
        for doc in _DOCUMENTS_BY_KB.get(kds_id, [])
        if _visible_in_completed_listing(doc)
        and not (
            isinstance(doc.get("_deleted_at"), (int, float))
            and doc["_deleted_at"] <= now
        )
    ]


def _normalize_mock_folder_path(path: Optional[str]) -> str:
    """Normalize one mock folder path to the AIDP relative form."""
    normalized = (path or "/").strip().replace("\\", "/")
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = "/" + "/".join(
        part for part in normalized.split("/") if part and part != "."
    )
    if not normalized:
        return "/"
    if ".." in normalized.split("/"):
        raise HTTPException(status_code=422, detail="folder_path must not contain '..'")
    return normalized


def _folder_parent(path: str) -> str:
    parent, _, _name = path.rpartition("/")
    return parent or "/"


def _folder_name(path: str) -> str:
    return path.rpartition("/")[2]


def _join_folder_path(parent: str, name: str) -> str:
    return f"/{name}" if parent == "/" else f"{parent}/{name}"


def _folder_id_for_path(path: str) -> int:
    """Stable mock folder id: root is 0, other paths get a deterministic hash."""
    if path == "/":
        return 0
    return (zlib.crc32(path.encode("utf-8")) % 900_000_000) + 1


def _folder_path_for_id(kds_id: str, folder_id: int) -> str | None:
    if folder_id == 0:
        return "/"
    return next(
        (
            path
            for path in _all_folder_paths(kds_id)
            if _folder_id_for_path(path) == folder_id
        ),
        None,
    )


def _folder_has_child_folders(kds_id: str, path: str) -> bool:
    return any(
        _folder_parent(candidate) == path and candidate != path
        for candidate in _all_folder_paths(kds_id)
    )


def _uuid_hex(value: Any) -> str:
    text = str(value or "")
    compact = text.replace("-", "")
    if len(compact) == 32 and all(ch in "0123456789abcdefABCDEF" for ch in compact):
        return compact.lower()
    return text


def _folder_tree_status(document: Dict[str, Any]) -> int:
    """Map the mock's task status to the new tree contract 1–6."""
    deleted_at = document.get("_deleted_at")
    if isinstance(deleted_at, (int, float)) and deleted_at > time.time():
        return 5
    if document.get("file_status") == 2:
        return 6
    status = _doc_effective_status(document)
    if status == 4:
        return 2
    if status == 5:
        return 4
    return status if isinstance(status, int) else 1


def _folder_records(kds_id: str) -> List[Dict[str, Any]]:
    return _FOLDERS_BY_KB.setdefault(kds_id, [])


def _all_folder_paths(kds_id: str) -> set[str]:
    """Return every folder path, including ancestors implied by nested files."""
    paths: set[str] = set()
    values = [record.get("folder_path") for record in _folder_records(kds_id)]
    values.extend(
        document.get("folder_path") or "/"
        for document in _DOCUMENTS_BY_KB.get(kds_id, [])
        if isinstance(document, dict)
    )
    for value in values:
        if not isinstance(value, str) or not value.startswith("/"):
            continue
        current = value.rstrip("/") or "/"
        while current != "/":
            paths.add(current)
            current = _folder_parent(current)
    return paths


def _folder_exists(kds_id: str, path: str) -> bool:
    if path == "/":
        return True
    return path in _all_folder_paths(kds_id)


def _folder_is_empty(kds_id: str, path: str) -> bool:
    prefix = f"{path}/"
    if any(
        isinstance(document, dict)
        and str(document.get("folder_path") or "/").startswith(prefix)
        for document in _DOCUMENTS_BY_KB.get(kds_id, [])
    ):
        return False
    return not any(
        folder_path.startswith(prefix)
        for folder_path in _all_folder_paths(kds_id)
    )


def _ensure_folder_records(kds_id: str, path: str) -> None:
    """Materialize a folder and its ancestors so empty folders survive moves."""
    current = _normalize_mock_folder_path(path)
    records = _folder_records(kds_id)
    known = {record.get("folder_path") for record in records}
    now = int(time.time())
    ancestors: List[str] = []
    while current != "/":
        ancestors.append(current)
        current = _folder_parent(current)
    for folder_path in reversed(ancestors):
        if folder_path not in known:
            records.append({"folder_path": folder_path, "create_time": now})
            known.add(folder_path)


def _rewrite_folder_prefix(kds_id: str, old_path: str, new_path: str) -> None:
    """Move a folder subtree by rewriting folder and document path prefixes."""
    old_prefix = f"{old_path}/"
    for record in _folder_records(kds_id):
        current = record.get("folder_path")
        if current == old_path:
            record["folder_path"] = new_path
        elif isinstance(current, str) and current.startswith(old_prefix):
            record["folder_path"] = f"{new_path}/{current[len(old_prefix):]}"
    for document in _DOCUMENTS_BY_KB.get(kds_id, []):
        if not isinstance(document, dict):
            continue
        current = document.get("folder_path") or "/"
        if current == old_path:
            document["folder_path"] = new_path
        elif isinstance(current, str) and current.startswith(old_prefix):
            document["folder_path"] = f"{new_path}/{current[len(old_prefix):]}"


_DERIVED_KB_FIELDS = frozenset(
    {
        "document_count",
        "update_time",
        "embedding_model",
        "rerank_model",
        "chunk_mode",
        "chunk_token_num",
        "chunk_overlap_num",
        "caption_enable",
        "is_multimodal",
        "topk",
        "llm_model_name",
        "created_by",
        "creator_name",
    }
)


def _public_kb_detail(kb: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror the live AIDP detail response, not the mock's internal record.

    The live service keeps chunking and embedding settings inside
    ``kms_config_str``, exposes ``top_k`` (with the underscore), nests the graph
    LLM model inside ``graph_config``, and does not return ``update_time``,
    ``rerank_model``, ``is_multimodal`` or any ``retrieve_default_topk``.
    """
    result = {
        key: value
        for key, value in kb.items()
        if not key.startswith("_") and key not in _DERIVED_KB_FIELDS
    }
    result["top_k"] = kb.get("top_k", kb.get("topk", 10))
    kms_config = kb.get("kms_config_str")
    if not (isinstance(kms_config, str) and kms_config.strip()):
        kms_config = {
            "chunk_token_num": kb.get("chunk_token_num", 512),
            "chunk_overlap_num": kb.get("chunk_overlap_num", 51),
            "embedding_model": kb.get(
                "embedding_model",
                "/models/FileEmbeddingModel_v0_1_1/v1.0.0/FileEmbeddingModel_v0_1_1",
            ),
            "caption_enable": kb.get(
                "caption_enable", 1 if kb.get("vlm_model") else 0
            ),
            "chunk_mode": kb.get("chunk_mode", 0),
        }
        kms_config = json.dumps(kms_config, ensure_ascii=False)
    result["kms_config_str"] = kms_config

    graph = kb.get("graph_config")
    if isinstance(graph, str):
        try:
            graph = json.loads(graph)
        except json.JSONDecodeError:
            graph = None
    if isinstance(graph, dict):
        graph = dict(graph)
        graph.pop("retrieve_default_topk", None)
        model_name = kb.get("llm_model_name")
        if isinstance(model_name, str) and model_name.strip():
            graph.setdefault("llm_model_name", model_name)
        result["graph_config"] = json.dumps(graph, ensure_ascii=False)
    else:
        result["graph_config"] = ""

    result["vlm_model"] = kb.get("vlm_model", "")
    result["similarity"] = kb.get("similarity", 0.0)
    result["is_exist_graph"] = bool(kb.get("is_exist_graph", False))
    result["is_personal"] = kb.get("is_personal", 0)
    result["state"] = kb.get("state", 4)
    result["role"] = kb.get("role", "Owner")
    result["user_name"] = kb.get("user_name")
    return result


def _find_document(kds_id: str, file_uuid: str) -> Optional[Dict[str, Any]]:
    found = next(
        (
            document
            for document in _DOCUMENTS_BY_KB.get(kds_id, [])
            if document.get("file_uuid") == file_uuid
        ),
        None,
    )
    if found is None:
        return None
    deleted_at = found.get("_deleted_at")
    if isinstance(deleted_at, (int, float)) and deleted_at <= time.time():
        return None
    return found


def _document_content(document: Dict[str, Any]) -> bytes:
    """Return the bytes AIDP would serve for a document download.

    Uploaded documents are returned unchanged, mirroring real AIDP. Documents
    that only exist as metadata (the seeded ones, or anything restored from the
    state file after a restart) have no payload, so they fall back to
    deterministic text that keeps the download contract testable.
    """
    payload = _DOCUMENT_PAYLOADS.get(str(document.get("file_uuid")))
    if payload is not None:
        return payload
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


# Extensions AIDP can render itself: those are served byte-for-byte, everything
# else is converted, which is why only these keep their extension in the name
# reported through ``X-File-Name``.
_NATIVE_PREVIEW_EXTENSIONS = {"docx", "xlsx", "pptx", "pdf", "txt"}


def _synthetic_pdf(text: str) -> bytes:
    """Build a minimal, valid single-page PDF standing in for a conversion.

    The mock cannot really convert a document, so a converted preview has to be
    answered with something a PDF viewer accepts. Offsets are computed here so
    the cross-reference table is correct and the file opens in pdf.js.
    """
    stream = f"BT /F1 12 Tf 40 60 Td ({text}) Tj ET".encode("ascii", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 120] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % index + body + b"\nendobj\n"

    xref_offset = len(pdf)
    pdf += b"xref\n0 %d\n" % (len(objects) + 1)
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += b"%010d 00000 n \n" % offset
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_offset,
    )
    return bytes(pdf)


def _preview_payload(document: Dict[str, Any]) -> tuple[bytes, str]:
    """Return ``(content, served_file_name)`` for a preview request.

    Mirrors AIDP: docx/xlsx/pptx/pdf/txt come back unchanged, every other format
    comes back as a PDF whose name replaces the uploaded extension. The served
    name is what the caller reads from ``X-File-Name``.
    """
    filename = str(document.get("file_name") or "document")
    stem, dot, extension = filename.rpartition(".")
    if dot and extension.lower() in _NATIVE_PREVIEW_EXTENSIONS:
        return _document_content(document), filename

    served_name = f"{stem or 'document'}.pdf"
    return _synthetic_pdf(f"AIDP conversion of {filename}"), served_name


def _attach_served_file_name(response: StreamingResponse, file_name: str) -> StreamingResponse:
    """Attach ``X-File-Name`` the way AIDP does: raw UTF-8 header bytes.

    Starlette encodes header values as latin-1, which a Chinese file name cannot
    survive, so the header is appended to ``raw_headers`` directly. Real AIDP
    sends these bytes as-is, and reproducing that is what keeps the proxy's
    non-ASCII handling covered by local runs.
    """
    response.raw_headers.append((b"x-file-name", file_name.encode("utf-8")))
    return response


# =============================================================================
# Document status helpers
# =============================================================================
def _channel_src_dir(kds_id: str) -> str:
    """Return the source directory of a knowledge base's ingestion channel."""
    return f"{_CHANNEL_ROOT}/{kds_id}"


def _kds_id_from_dir_path(dir_path: Optional[str]) -> Optional[str]:
    """Reverse ``_channel_src_dir`` so a History request maps back to one KB."""
    if not isinstance(dir_path, str):
        return None
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
    chunk_token_num: int = 512
    chunk_overlap_num: int = 51
    chunk_mode: int = 0
    is_personal: int = 0
    topk: int = 10
    similarity: float = 0.0
    caption_enable: int = 0
    vlm_model: str = ""
    is_exist_graph: bool = False
    graph_config: Optional[str] = None
    sensitive_intercept_enable: int = 0


class UpdateKbBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    chunk_mode: Optional[int] = None
    chunk_token_num: Optional[int] = None
    chunk_overlap_num: Optional[int] = None
    topk: Optional[int] = None
    caption_enable: Optional[int] = None
    vlm_model: Optional[str] = None
    is_exist_graph: Optional[bool] = None
    graph_config: Optional[str] = None
    sensitive_intercept_enable: Optional[int] = None


class DocHistoryBody(BaseModel):
    """Body of POST .../KnowledgeFiles/History (channel + directory scoped)."""

    fs_id: Optional[str] = None
    dir_path: Optional[str] = None
    page: int = 1
    page_size: Optional[int] = Field(default=None, ge=1, le=100)
    status: Optional[int] = Field(default=None, ge=0, le=5)
    keyword: Optional[str] = Field(default=None, max_length=200)


class RetryDocumentsBody(BaseModel):
    retry_file_info: List[Dict[str, str]] = Field(..., min_length=1)


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


class HybridSearchConfig(BaseModel):
    """Per-channel knobs for the vector/full-text part of a FusionSearch call."""

    vector_candidates: int = Field(default=10, ge=1, le=500)
    full_text_candidates: int = Field(default=10, ge=1, le=500)
    hybrid_top_k: int = Field(0, ge=0, le=100)
    vector_score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    full_text_score_threshold: float = Field(0.0, ge=0.0, le=1.0)


class GraphSearchConfig(BaseModel):
    """Per-channel knobs for the graph part of a FusionSearch call."""

    graph_top_k: int = Field(0, ge=0, le=100)
    graph_score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    graph_reranking_enable: bool = True


class FusionSearchRequest(BaseModel):
    """FusionSearch request mirroring the current AIDP wire contract.

    ``topk``/``multi_modal_enable`` are the outbound names; the retired
    ``top_k``/``multi_modal`` aliases are accepted only so historical clients
    keep working in tests, and are never mixed with the new names in a single
    payload.
    """

    query: str = Field(min_length=1)
    kds_list: List[str] = Field(min_length=1, max_length=10)
    search_method: str = "vector_search|full_text_search|graph_search"
    reranking_enable: bool = False
    reranking_mode: Optional[Literal["performance", "high_accuracy", "jargon_coverage"]] = None
    rewrite_enable: bool = False
    query_expansion_enable: bool = False
    related_search_enable: bool = False
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    topk: int = Field(10, ge=1, le=100)
    multi_modal_enable: bool = False
    hybrid_search_config: Optional[HybridSearchConfig] = None
    graph_search_config: Optional[GraphSearchConfig] = None
    metadata_condition: Optional[MetadataCondition] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_aliases(cls, data: Any) -> Any:
        """Translate the pre-upgrade names once, rejecting mixed payloads."""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        for legacy, current in (("top_k", "topk"), ("multi_modal", "multi_modal_enable")):
            if legacy in payload:
                if current in payload and payload[current] != payload[legacy]:
                    raise ValueError(f"{current} and legacy {legacy} disagree")
                payload.setdefault(current, payload.pop(legacy))
        return payload

    @model_validator(mode="after")
    def _validate_method_and_quota(self) -> "FusionSearchRequest":
        """Validate the method set and the cross-channel quota relations."""
        channels = set(_RETRIEVAL_CHANNELS if self.search_method == "hybrid_search"
                       else self.search_method.split("|"))
        unknown = channels - set(_RETRIEVAL_CHANNELS)
        if not channels or unknown:
            raise ValueError(f"search_method must combine {sorted(_RETRIEVAL_CHANNELS)}")
        hybrid = bool(channels & {"vector_search", "full_text_search"})
        graph = "graph_search" in channels
        if hybrid and self.hybrid_search_config is None:
            raise ValueError("hybrid_search_config is required for vector/full-text retrieval")
        if graph and self.graph_search_config is None:
            raise ValueError("graph_search_config is required for graph retrieval")
        if not hybrid and self.hybrid_search_config is not None:
            raise ValueError("hybrid_search_config must not be sent for pure graph retrieval")
        if not graph and self.graph_search_config is not None:
            raise ValueError("graph_search_config must not be sent without graph retrieval")
        h = self.hybrid_search_config.hybrid_top_k if self.hybrid_search_config else 0
        g = self.graph_search_config.graph_top_k if self.graph_search_config else 0
        if hybrid and h > self.topk:
            raise ValueError("hybrid_top_k must not exceed topk")
        if graph and g > self.topk:
            raise ValueError("graph_top_k must not exceed topk")
        if hybrid and graph and h > 0 and g > 0 and h + g > self.topk:
            raise ValueError("hybrid_top_k + graph_top_k must not exceed topk")
        return self


class RemoveFilesBody(BaseModel):
    file_uuids: List[uuid.UUID] = Field(..., min_length=1)


class CountFilesBody(BaseModel):
    """Body of POST .../KnowledgeFiles/Count (all fields optional)."""

    fs_id: Optional[str] = None
    dir_path: Optional[str] = None
    keyword: Optional[str] = Field(default=None, max_length=200)


class DownloadFileBody(BaseModel):
    file_uuid: uuid.UUID = Field(...)


class CreateSensitiveWordBody(BaseModel):
    word: str = Field(..., min_length=1, max_length=64)
    mode: Literal["BLACK", "WHITE"]
    description: str = Field(..., min_length=1, max_length=512)

    @model_validator(mode="after")
    def strip_fields(self):
        self.word = self.word.strip()
        self.description = self.description.strip()
        if not self.word or not self.description:
            raise ValueError("word and description must not be blank")
        return self


class UpdateSensitiveWordBody(BaseModel):
    word: Optional[str] = Field(default=None, max_length=64)
    mode: Optional[Literal["BLACK", "WHITE"]] = None
    description: Optional[str] = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def require_a_change(self):
        if self.word is None and self.mode is None and self.description is None:
            raise ValueError("At least one field must be provided")
        if self.word is not None:
            self.word = self.word.strip()
            if not self.word:
                raise ValueError("word must not be blank")
        if self.description is not None:
            self.description = self.description.strip()
            if not self.description:
                raise ValueError("description must not be blank")
        return self



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
    # Match AIDP's catalog response: file counts come from the dedicated
    # KnowledgeFiles/Count endpoint, not from each KB row.
    items = [
        {key: value for key, value in kb.items() if key != "document_count"}
        for kb in all_items[start:end]
    ]

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
    body: Optional[CountFilesBody] = None,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Count documents in a knowledge base.

    AIDP uses POST .../KnowledgeBases/{kds_id}/KnowledgeFiles/Count. The body
    is optional; when it carries ``keyword`` the count is filtered, matching the
    live service.
    """
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    docs = _active_documents(kds_id)
    keyword = body.keyword.strip().casefold() if body and body.keyword else ""
    if keyword:
        docs = [
            doc for doc in docs
            if keyword in str(doc.get("file_name") or "").casefold()
        ]
    count = len(docs)
    logger.info("COUNT DOCS  kds_id=%s count=%d", kds_id, count)
    return JSONResponse(content={"count": count})


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


@app.get(f"{_KB_PREFIX}/GraphConfigTemplate")
def graph_config_template(
    language: str = Query("chinese", pattern="^(chinese|english)$"),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    return JSONResponse(content=_graph_template(language))


@app.post("/_mock/upload-seconds")
def set_upload_seconds(
    seconds: float = Query(10.0, ge=0.0, le=600.0, description="Upload response delay in seconds"),
) -> JSONResponse:
    """Delay each batch once without blocking other mock requests."""
    global _UPLOAD_SECONDS
    _UPLOAD_SECONDS = seconds
    logger.info("MOCK CONFIG  upload response delay = %s", seconds)
    return JSONResponse(content={"upload_seconds": _UPLOAD_SECONDS})


@app.post("/_mock/file-faults")
def set_file_faults(
    query_seconds: float = Query(0.0, ge=0.0, le=30.0),
    query_fail: bool = Query(False),
    delete_fail: bool = Query(False),
) -> JSONResponse:
    """Configure transient file-page acceptance scenarios without changing data."""
    global _FILE_QUERY_SECONDS, _FILE_QUERY_FAIL, _FILE_DELETE_FAIL
    _FILE_QUERY_SECONDS = query_seconds
    _FILE_QUERY_FAIL = query_fail
    _FILE_DELETE_FAIL = delete_fail
    return JSONResponse(content={
        "query_seconds": query_seconds,
        "query_fail": query_fail,
        "delete_fail": delete_fail,
    })


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

    # Match AIDP's detail response: file counts come from the Count endpoint
    # and configuration fields stay inside kms_config_str / graph_config.
    result = _public_kb_detail(kb)

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
    if body.chunk_token_num is not None:
        kb["chunk_token_num"] = body.chunk_token_num
    if body.chunk_overlap_num is not None:
        kb["chunk_overlap_num"] = body.chunk_overlap_num
    if body.topk is not None:
        kb["topk"] = body.topk
    if body.caption_enable is not None:
        kb["caption_enable"] = body.caption_enable
    if body.vlm_model is not None:
        kb["vlm_model"] = body.vlm_model
    if body.sensitive_intercept_enable is not None:
        kb["sensitive_intercept_enable"] = body.sensitive_intercept_enable
    if body.is_exist_graph is not None:
        # Disabling is permanent: a disabled graph can never be re-enabled.
        if body.is_exist_graph and not kb.get("is_exist_graph"):
            raise HTTPException(400, "Knowledge graph cannot be re-enabled once disabled")
        kb["is_exist_graph"] = body.is_exist_graph
    if body.graph_config is not None:
        # Partial update: the backend already validated the edited fields, so
        # only the key names are checked here. The graph_config JSON string
        # contains only modifiable fields (non-modifiable template fields like
        # domain/prompt_language/prompt_text are stripped by the backend).
        try:
            graph_update = json.loads(body.graph_config)
        except ValueError as exc:
            raise HTTPException(400, "graph_config must be a JSON string") from exc
        allowed = {p["param_key"] for p in _graph_template("chinese")["value"] if p.get("is_modifiable")} | {"llm_model_name"}
        if not isinstance(graph_update, dict) or set(graph_update) - allowed:
            raise HTTPException(400, "Unrecognized graph configuration parameter")
        current = kb.get("graph_config")
        if isinstance(current, str):
            try:
                current = json.loads(current)
            except ValueError:
                current = {}
        if not isinstance(current, dict):
            current = {}
        current.update(graph_update)
        kb["graph_config"] = current
        if isinstance(current.get("llm_model_name"), str):
            kb["llm_model_name"] = current["llm_model_name"]
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
    _FOLDERS_BY_KB.pop(kds_id, None)

    logger.info("DELETE  kds_id=%s", kds_id)
    _save_state()
    return JSONResponse(content={"success": True})


# =============================================================================
# Folder Management
# =============================================================================


class CreateFolderBody(BaseModel):
    parent_folder_path: str
    folder_name: str


class RenameFolderBody(BaseModel):
    parent_folder_path: str
    old_folder_name: str
    new_folder_name: str


class MoveFolderBody(BaseModel):
    src_parent_folder_path: str
    folder_name: str
    target_parent_folder_path: str
    target_parent_folder_id: int
    merge_on_conflict: bool = False


class MoveFilesBody(BaseModel):
    file_uuids: List[str]
    target_folder_path: str
    target_folder_id: int


class RenameFileBody(BaseModel):
    file_uuid: str
    new_file_name: str


def _require_kb(kds_id: str) -> None:
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")


def _name_conflict(path: str) -> HTTPException:
    """AIDP 1089: a folder or file already uses this name in the location."""
    return HTTPException(
        status_code=409,
        detail={
            "code": 1089,
            "message": f"name already exists: {path}",
        },
    )


@app.get(f"{_KB_PREFIX}/{{kds_id}}/Folders/{{folder_id}}")
def get_folder_tree(
    kds_id: str,
    folder_id: int,
    folder_path: str = Query(default="/"),
    include_files: bool = Query(default=False),
    keyword: Optional[str] = Query(default=None, max_length=200),
    file_type: Optional[str] = Query(default=None, max_length=32),
    file_status: Optional[str] = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Return direct subfolders and, when requested, current-folder files."""
    _check_auth(authorization)
    _require_kb(kds_id)
    normalized_path = _normalize_mock_folder_path(folder_path)
    if not _folder_exists(kds_id, normalized_path):
        raise HTTPException(status_code=404, detail=f"Folder {normalized_path} not found")
    if _folder_id_for_path(normalized_path) != folder_id:
        raise HTTPException(status_code=404, detail=f"Folder id {folder_id} not found")

    all_paths = _all_folder_paths(kds_id)
    direct_folders = sorted(
        (
            path
            for path in all_paths
            if _folder_parent(path) == normalized_path and path != normalized_path
        ),
        key=str.casefold,
    )
    folders = [
        {
            "folder_name": _folder_name(path),
            "folder_id": _folder_id_for_path(path),
            "has_child_folders": _folder_has_child_folders(kds_id, path),
        }
        for path in direct_folders
    ]

    documents: List[Dict[str, Any]] = []
    if include_files:
        documents = [
            document
            for document in _active_documents(kds_id)
            if (document.get("folder_path") or "/") == normalized_path
        ]
        normalized_keyword = keyword.strip().casefold() if isinstance(keyword, str) else ""
        if normalized_keyword:
            documents = [
                document
                for document in documents
                if normalized_keyword in str(document.get("file_name") or "").casefold()
            ]
        if file_type and file_type.strip():
            wanted_type = file_type.strip().casefold().lstrip(".")
            documents = [
                document
                for document in documents
                if str(document.get("file_type") or "").casefold().lstrip(".") == wanted_type
            ]
        if file_status and file_status.strip():
            wanted_status = file_status.strip()
            documents = [
                document
                for document in documents
                if str(_folder_tree_status(document)) == wanted_status
            ]
        documents.sort(key=lambda document: str(document.get("file_name") or "").casefold())

    total = len(documents)
    start_index = (page - 1) * page_size
    items = [
        {
            "file_uuid": _uuid_hex(document.get("file_uuid")),
            "file_name": document.get("file_name"),
            "file_type": document.get("file_type"),
            "file_size": document.get("file_size"),
            "status": _folder_tree_status(document),
            "first_upload_time": document.get("first_upload_time")
            or document.get("create_time"),
            "update_time": document.get("update_time") or document.get("first_upload_time"),
        }
        for document in documents[start_index : start_index + page_size]
    ]
    return JSONResponse(
        content={
            "folder_id": folder_id,
            "folder_path": normalized_path,
            "folders": folders,
            "files": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "value": items,
            },
        }
    )


@app.post(f"{_KB_PREFIX}/{{kds_id}}/Folders/{{parent_folder_id}}")
def create_folder(
    kds_id: str,
    parent_folder_id: int,
    body: CreateFolderBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Create one folder below an existing parent folder (name must be unique)."""
    _check_auth(authorization)
    _require_kb(kds_id)
    parent = _normalize_mock_folder_path(body.parent_folder_path)
    name = body.folder_name.strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="folder_name must not contain /")
    if not _folder_exists(kds_id, parent):
        raise HTTPException(status_code=404, detail=f"Folder {parent} not found")
    if _folder_id_for_path(parent) != parent_folder_id:
        raise HTTPException(status_code=404, detail=f"Folder id {parent_folder_id} not found")
    new_path = _join_folder_path(parent, name)
    if _folder_exists(kds_id, new_path):
        raise _name_conflict(new_path)
    _ensure_folder_records(kds_id, new_path)
    _save_state()
    logger.info("CREATE FOLDER  kds_id=%s path=%s", kds_id, new_path)
    return JSONResponse(
        content={
            "folder_path": new_path,
            "folder_id": _folder_id_for_path(new_path),
        }
    )


@app.patch(f"{_KB_PREFIX}/{{kds_id}}/Folders/{{folder_id}}")
def rename_folder(
    kds_id: str,
    folder_id: int,
    body: RenameFolderBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Rename one folder addressed by its own FolderId."""
    _check_auth(authorization)
    _require_kb(kds_id)
    parent = _normalize_mock_folder_path(body.parent_folder_path)
    old_name = body.old_folder_name.strip()
    new_name = body.new_folder_name.strip()
    if not new_name or "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=400, detail="invalid new_folder_name")
    source = _join_folder_path(parent, old_name)
    if not _folder_exists(kds_id, source) or source == "/":
        raise HTTPException(status_code=404, detail=f"Folder {source} not found")
    if _folder_id_for_path(source) != folder_id:
        raise HTTPException(status_code=404, detail=f"Folder id {folder_id} not found")
    destination = _join_folder_path(parent, new_name)
    if destination != source and destination in _all_folder_paths(kds_id):
        raise _name_conflict(destination)
    _rewrite_folder_prefix(kds_id, source, destination)
    _save_state()
    return JSONResponse(content={"folder_path": destination})


@app.delete(f"{_KB_PREFIX}/{{kds_id}}/Folders/{{folder_id}}")
def delete_folder(
    kds_id: str,
    folder_id: int,
    folder_path: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Response:
    """Delete an empty folder addressed by its own FolderId."""
    _check_auth(authorization)
    _require_kb(kds_id)
    target = (
        _normalize_mock_folder_path(folder_path)
        if folder_path is not None
        else _folder_path_for_id(kds_id, folder_id)
    )
    if target is None or target == "/":
        raise HTTPException(status_code=404, detail=f"Folder id {folder_id} not found")
    if _folder_id_for_path(target) != folder_id:
        raise HTTPException(status_code=404, detail=f"Folder id {folder_id} not found")
    if not _folder_exists(kds_id, target):
        raise HTTPException(status_code=404, detail=f"Folder {target} not found")
    if not _folder_is_empty(kds_id, target):
        raise HTTPException(
            status_code=400,
            detail="folder is not empty (code 1090)",
        )
    _FOLDERS_BY_KB[kds_id] = [
        record
        for record in _folder_records(kds_id)
        if record.get("folder_path") != target
    ]
    _save_state()
    logger.info("DELETE FOLDER  kds_id=%s path=%s", kds_id, target)
    return Response(status_code=204)


@app.post(f"{_KB_PREFIX}/{{kds_id}}/Folders/{{folder_id}}/Move")
def move_folder(
    kds_id: str,
    folder_id: int,
    body: MoveFolderBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Move one folder (with its subtree) using the new target_* fields."""
    _check_auth(authorization)
    _require_kb(kds_id)
    parent = _normalize_mock_folder_path(body.src_parent_folder_path)
    name = body.folder_name.strip()
    target = _normalize_mock_folder_path(body.target_parent_folder_path)
    source = _join_folder_path(parent, name)
    if source == "/" or not _folder_exists(kds_id, source):
        raise HTTPException(status_code=404, detail=f"Folder {source} not found")
    if _folder_id_for_path(source) != folder_id:
        raise HTTPException(status_code=404, detail=f"Folder id {folder_id} not found")
    if not _folder_exists(kds_id, target):
        raise HTTPException(status_code=404, detail=f"Folder {target} not found")
    if _folder_id_for_path(target) != body.target_parent_folder_id:
        raise HTTPException(status_code=404, detail="target folder id not found")
    if target == source or target.startswith(f"{source}/"):
        raise HTTPException(
            status_code=400,
            detail="cannot move a folder into itself (code 1091)",
        )
    destination = _join_folder_path(target, name)
    if destination in _all_folder_paths(kds_id) and not body.merge_on_conflict:
        raise _name_conflict(destination)
    _rewrite_folder_prefix(kds_id, source, destination)
    _save_state()
    return JSONResponse(
        content={"folder_path": destination, "conflict_paths": []}
    )


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Move")
def move_files(
    kds_id: str,
    body: MoveFilesBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Move knowledge files to a folder with per-file outcomes."""
    _check_auth(authorization)
    _require_kb(kds_id)
    target = _normalize_mock_folder_path(body.target_folder_path)
    if not _folder_exists(kds_id, target):
        raise HTTPException(status_code=404, detail=f"Folder {target} not found")
    if _folder_id_for_path(target) != body.target_folder_id:
        raise HTTPException(status_code=404, detail="target folder id not found")
    documents = _DOCUMENTS_BY_KB.setdefault(kds_id, [])
    success_list: List[Dict[str, str]] = []
    failed_list: List[Dict[str, str]] = []
    for file_uuid in body.file_uuids:
        document = next(
            (
                item
                for item in documents
                if _uuid_hex(item.get("file_uuid")) == _uuid_hex(file_uuid)
            ),
            None,
        )
        if document is None:
            failed_list.append(
                {
                    "file_uuid": str(file_uuid),
                    "reason_zh": "文件不存在",
                    "reason_en": "File not found",
                }
            )
            continue
        document["folder_path"] = target
        success_list.append(
            {
                "file_uuid": _uuid_hex(file_uuid),
                "file_path": _join_folder_path(
                    target, str(document.get("file_name") or "")
                ),
            }
        )
    _save_state()
    return JSONResponse(
        content={
            "summary": {
                "total": len(body.file_uuids),
                "success": len(success_list),
                "failed": len(failed_list),
            },
            "success_list": success_list,
            "failed_list": failed_list,
        }
    )


@app.patch(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles")
def rename_file(
    kds_id: str,
    body: RenameFileBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Rename one knowledge file and return its new logical path."""
    _check_auth(authorization)
    _require_kb(kds_id)
    document = _find_document(kds_id, body.file_uuid)
    if document is None:
        raise HTTPException(status_code=404, detail="file not found")
    new_name = body.new_file_name.strip()
    if not new_name or "/" in new_name or "\\" in new_name:
        raise HTTPException(status_code=422, detail="invalid new_file_name")
    folder_path = document.get("folder_path") or "/"
    if any(
        other is not document
        and (other.get("folder_path") or "/") == folder_path
        and other.get("file_name") == new_name
        for other in _DOCUMENTS_BY_KB.get(kds_id, [])
    ):
        raise _name_conflict(_join_folder_path(folder_path, new_name))
    document["file_name"] = new_name
    _save_state()
    return Response(status_code=204)


# =============================================================================
# Document Management
# =============================================================================


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Upload")
async def upload_documents(
    kds_id: str,
    files: List[UploadFile] = File(...),
    target_folder_path: Optional[str] = Form(default=None),
    target_folder_id: Optional[int] = Form(default=None),
    relative_paths: Optional[List[str]] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Upload documents using the new target_folder_path + relative directory fields."""
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    normalized_target = _normalize_mock_folder_path(target_folder_path or "/")
    if not _folder_exists(kds_id, normalized_target):
        raise HTTPException(
            status_code=404,
            detail=f"Folder {normalized_target} not found",
        )
    if target_folder_id is not None and _folder_id_for_path(normalized_target) != target_folder_id:
        raise HTTPException(status_code=404, detail="target folder id not found")

    if _UPLOAD_SECONDS > 0:
        await asyncio.sleep(_UPLOAD_SECONDS)

    success_docs: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for index, f in enumerate(files):
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
            relative_dir = (
                (relative_paths[index] or "").replace("\\", "/").strip("/")
                if relative_paths and index < len(relative_paths)
                else ""
            )
            if any(segment in {".", ".."} for segment in relative_dir.split("/")):
                raise ValueError("relative_paths must not contain '.' or '..'")
            folder_path = (
                _join_folder_path(normalized_target, relative_dir)
                if relative_dir
                else normalized_target
            )
            _ensure_folder_records(kds_id, folder_path)
            file_name = f.filename or "unknown"
            if any(
                (document.get("folder_path") or "/") == folder_path
                and document.get("file_name") == file_name
                for document in _DOCUMENTS_BY_KB.get(kds_id, [])
            ):
                failed.append({
                    "file_name": file_name,
                    "reason_zh": "文件已存在，请重命名或删除已有文件",
                    "reason_en": "File already exists. Please rename or delete the existing file.",
                    "code": 1089,
                    "relative_path": relative_dir,
                })
                continue
            doc = {
                "file_uuid": uuid.uuid4().hex,
                "file_ino_no": file_ino_no,
                "file_name": file_name,
                "file_size": len(content),
                "file_type": (f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else "bin"),
                "create_time": int(time.time()),
                "update_time": int(time.time()),
                "folder_path": folder_path,
                # Uploaded files enter the ingestion pipeline immediately: the
                # legacy list endpoint hides them until the timer elapses, while
                # the history endpoint reports them as PROCESSING.
                "status": STATUS_PROCESSING,
                "processing_until": time.time() + _PROCESSING_SECONDS,
            }
            _DOCUMENTS_BY_KB.setdefault(kds_id, []).append(doc)
            _DOCUMENT_PAYLOADS[doc["file_uuid"]] = content
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
                "file_uuid": doc["file_uuid"],
                "file_name": doc["file_name"],
                "file_type": doc["file_type"],
                "file_size": doc["file_size"],
                "file_ino_no": doc["file_ino_no"],
                "storage_name": f"{doc['file_uuid']}_{doc['file_name']}",
                "file_path": _join_folder_path(
                    doc["folder_path"], doc["file_name"]
                ),
                "folder_id": _folder_id_for_path(doc["folder_path"]),
                "relative_path": (
                    ""
                    if doc["folder_path"] == normalized_target
                    else doc["folder_path"][len(normalized_target):].strip("/")
                ),
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

    if _FILE_QUERY_SECONDS:
        time.sleep(_FILE_QUERY_SECONDS)
    if _FILE_QUERY_FAIL:
        raise HTTPException(503, detail={
            "code": "130501", "message": "Mock file query service unavailable",
        })

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    all_docs = _active_documents(kds_id)
    normalized_keyword = keyword.strip().casefold() if isinstance(keyword, str) else ""
    if normalized_keyword:
        all_docs = [
            doc for doc in all_docs
            if normalized_keyword in str(doc.get("file_name") or "").casefold()
        ]
    start = (page - 1) * page_size
    end = start + page_size
    items = [
        {**_public_document(doc), "file_status": int(doc.get("file_status", 0))}
        for doc in all_docs[start:end]
    ]

    # The live service returns next_link on every page, including the last and
    # empty ones; callers must use the row count (or Count) to decide whether
    # another page exists. Keep the shape faithful so local tests do not rely
    # on next_link being absent at the end.
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
    success_list: List[Dict[str, str]] = []
    failed_list: List[Dict[str, str]] = []
    now = time.time()
    for raw_file_uuid in body.file_uuids:
        file_uuid = str(raw_file_uuid)
        matched = next(
            (document for document in documents if document.get("file_uuid") == file_uuid),
            None,
        )
        already_deleted = (
            matched is not None
            and isinstance(matched.get("_deleted_at"), (int, float))
            and matched["_deleted_at"] <= now
        )
        if matched is None or already_deleted or _FILE_DELETE_FAIL:
            if matched is not None and _FILE_DELETE_FAIL:
                # Deletion failed upstream: keep the row visible and expose the
                # failed state the detail page renders.
                matched["file_status"] = 2
            failed_list.append({
                "file_uuid": file_uuid,
                **({"code": "130501", "message": "Mock file removal failed"}
                   if _FILE_DELETE_FAIL else {}),
            })
            continue
        # Removal is asynchronous in the live service: the row stays in
        # KnowledgeFiles with file_status=1 for a short window, then disappears.
        matched["file_status"] = 1
        matched["_deleted_at"] = now + _FILE_DELETE_SECONDS
        success_list.append({"file_uuid": file_uuid})

    _DOCUMENTS_BY_KB[kds_id] = documents
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


@app.get(f"{_KB_PREFIX}/{{kds_id}}/OcrAnnotate/{{file_uuid}}")
def preview_document(
    kds_id: str,
    file_uuid: str,
    authorization: Optional[str] = Header(default=None),
) -> StreamingResponse:
    """Serve one document the way AIDP's preview endpoint does.

    The served name travels in ``X-File-Name`` because a converted document is
    answered with a PDF whose name replaces the uploaded extension; the
    disposition stays ``attachment`` upstream, so the proxy under test has to
    build its own ``inline`` header instead of forwarding this one.
    """
    _check_auth(authorization)

    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")

    document = _find_document(kds_id, str(file_uuid))
    if document is None:
        raise HTTPException(status_code=404, detail=f"File {file_uuid} not found")

    content, served_name = _preview_payload(document)
    content_type = mimetypes.guess_type(served_name)[0] or "application/octet-stream"
    response_headers = {
        "X-File-Size": str(len(content)),
        "Content-Disposition": _content_disposition(served_name),
    }

    async def content_stream():
        for offset in range(0, len(content), 8 * 1024):
            yield content[offset : offset + 8 * 1024]

    return _attach_served_file_name(
        StreamingResponse(
            content_stream(),
            media_type=content_type,
            headers=response_headers,
        ),
        served_name,
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
    file-name filtering, and reports summary counts for the filtered set.
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
    # Real AIDP lists files that are still being processed first and pages the
    # directory, which is what lets more simultaneous uploads than fit in one
    # page spill onto the next. Mirrored here, so a caller that reads only the
    # first page is caught locally instead of in production. The sort is stable,
    # so documents keep their insertion order inside each group.
    all_recent_items.sort(key=lambda item: item["status"] in _TERMINAL_STATUSES)
    items = list(all_recent_items)
    normalized_keyword = body.keyword.strip().casefold() if isinstance(body.keyword, str) else ""
    if normalized_keyword:
        items = [
            item for item in items
            if normalized_keyword in str(item.get("file_name") or "").casefold()
        ]
    # The live service computes total_record_count after the keyword filter
    # but before the status filter.
    keyword_items = list(items)
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
    stats = {
        "total_record_count": len(keyword_items),
        "success_record_count": sum(1 for item in items if item["status"] == 1),
        "processing_record_count": sum(1 for item in items if item["status"] == 2),
        "failed_record_count": sum(1 for item in items if item["status"] in (3, 5)),
        "waiting_record_count": sum(1 for item in items if item["status"] == 4),
    }
    page = body.page if isinstance(body.page, int) and body.page > 0 else 1
    page_size = body.page_size or _HISTORY_PAGE_SIZE
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    # next_link is always present in the live service, including on the last
    # page, and it does not preserve the status filter.
    next_link = (
        f"{_KB_PREFIX}/{kds_id}/KnowledgeFiles/History?page={page + 1}"
        f"&page_size={page_size}"
    )
    if normalized_keyword:
        next_link += f"&keyword={quote(body.keyword.strip(), safe='')}"
    logger.info(
        "FILE HISTORY  kds_id=%s fs_id=%s dir_path=%s page=%d returned=%d total=%d",
        kds_id, body.fs_id, body.dir_path, page, len(page_items), len(items),
    )
    return JSONResponse(content={
        "value": page_items,
        "total_count": len(page_items),
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

    success_list: List[Dict[str, str]] = []
    failed_list: List[Dict[str, str]] = []
    retryable = {3, 5, "3", "5", STATUS_FAILED, "VECTOR_INGESTION_FAILED", "GRAPH_INGESTION_FAILED"}
    file_uuids = [entry.get("file_uuid") for entry in body.retry_file_info if isinstance(entry, dict)]
    for file_uuid in dict.fromkeys(file_uuids):
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
    # ``retrieval_sources`` marks which channels can actually reach a chunk.
    # ``aidp-kb-product`` has no graph, so graph-only retrieval legitimately
    # returns nothing for it instead of silently falling back to vector.
    "aidp-kb-product": [
        {
            "id": 10001,
            "score": 0.96,
            "title": "AIDP产品介绍.pdf",
            "text": "AIDP Search provides low-latency retrieval across selected enterprise knowledge bases.",
            "metadata": {
                "knowledge_base_id": "aidp-kb-product", "section": "overview",
                "source": "产品资料", "count": 0, "enabled": False,
                "tags": ["知识库", "问答"],
                "standards": {"TEST_STANDARD": {"level_id": "TEST_E", "level_name": "E", "authority": "mock"}},
                # AIDP's fixed original-file identity contract.
                "kds_id": "aidp-kb-product",
                "file_uuid": "00000000-0000-4000-8000-000000000101",
            },
            "chunk_type": "text",
            "file_url": "",
            "pages": [1],
            "retrieval_sources": ["vector_search", "full_text_search"],
        },
        {
            "id": 10002, "score": 0.94, "title": "AIDP产品介绍.pdf",
            "text": "AIDP Search keeps each retrieval chunk independent so citations can identify their own metadata snapshot.",
            "metadata": {
                "knowledge_base_id": "aidp-kb-product", "section": "citations",
                "count": 1, "enabled": True,
                "kds_id": "aidp-kb-product",
                "file_uuid": "00000000-0000-4000-8000-000000000101",
            },
            "chunk_type": "text", "file_url": "", "pages": [2],
            "retrieval_sources": ["vector_search"],
        },
    ],
    "aidp-kb-faq": [
        {
            "id": 30001,
            "score": 0.93,
            "title": "常见问题汇总.txt",
            "text": "If no results are returned, verify the selected knowledge base IDs and API key.",
            "metadata": {
                "knowledge_base_id": "aidp-kb-faq", "section": "troubleshooting",
                "kds_id": "aidp-kb-faq",
                "file_uuid": "00000000-0000-4000-8000-000000000001",
            },
            "chunk_type": "text",
            "file_url": "",
            "pages": [1],
            "retrieval_sources": ["vector_search", "full_text_search", "graph_search"],
        },
        {
            "id": 30002,
            "score": 0.985,
            "title": "肝脏医学影像.jpg",
            "text": "Liver image for validating AIDP multi-modal retrieval image return pathway.",
            "metadata": {
                "knowledge_base_id": "aidp-kb-faq", "section": "liver-image-demo",
                "kds_id": "aidp-kb-faq",
                "file_uuid": "00000000-0000-4000-8000-000000000008",
            },
            "chunk_type": "image",
            "file_url": _MOCK_IMAGE_URLS[0],
            "pages": [6],
            "retrieval_sources": ["vector_search", "graph_search"],
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
    """Handle FusionSearch requests with the current per-channel contract.

    Channel behaviour mirrors what the real service does for a mixed corpus:

    * A channel only contributes chunks when it is selected. Chunks are tagged
      with the ``retrieval_sources`` they can be reached through (default
      ``vector_search``); graph retrieval only returns chunks whose knowledge
      base actually has a graph, and skips silently otherwise - never falling
      back to another channel.
    * Candidates cap each channel's pre-rerank pool, the per-channel thresholds
      filter that pool, ``score_threshold`` filters the merged result and
      ``topk`` truncates the final answer. A ``0`` cap means "no separate cap"
      and is not a zero quota.
    * ``retrieval_source.methods`` reports the channels that actually produced
      the hit, which may be fewer than the requested set.
    """
    _check_auth(authorization)

    channels = set(_RETRIEVAL_CHANNELS if request.search_method == "hybrid_search"
                   else request.search_method.split("|"))
    hybrid = request.hybrid_search_config
    graph = request.graph_search_config
    query_terms = [t.strip().lower() for t in request.query.split() if t.strip()]
    hits: List[Dict[str, Any]] = []

    for kb_id in request.kds_list:
        kb = _KNOWLEDGE_BASES.get(kb_id, {})
        graph_available = bool(kb.get("is_exist_graph"))
        for chunk in _CHUNKS_BY_KB.get(kb_id, []):
            if not _match_metadata(chunk, request.metadata_condition):
                continue
            if not request.multi_modal_enable and chunk.get("chunk_type") == "image":
                continue

            haystack = f"{chunk.get('title', '')} {chunk.get('text', '')}".lower()
            boost = min(0.05 * sum(1 for t in query_terms if t in haystack), 0.15)
            base_score = round(float(chunk.get("score", 0.5)) + boost, 4)
            reachable = [source for source in chunk.get("retrieval_sources", ["vector_search"])
                         if source in channels and (source != "graph_search" or graph_available)]
            if not reachable:
                continue

            per_source: List[tuple[str, float]] = []
            for source in reachable:
                if source == "vector_search":
                    threshold = hybrid.vector_score_threshold if hybrid else 0.0
                elif source == "full_text_search":
                    threshold = hybrid.full_text_score_threshold if hybrid else 0.0
                else:
                    threshold = graph.graph_score_threshold if graph else 0.0
                if base_score >= threshold:
                    per_source.append((source, base_score))
            if not per_source:
                continue
            if base_score < request.score_threshold:
                continue

            hits.append({
                "chunk": chunk,
                "score": base_score,
                "sources": sorted({source for source, _ in per_source}),
            })

    # Per-channel candidate caps: keep the strongest N per channel, then merge.
    capped: List[Dict[str, Any]] = []
    for source in _RETRIEVAL_CHANNELS:
        limit = None
        if source == "vector_search" and hybrid:
            limit = hybrid.vector_candidates
        elif source == "full_text_search" and hybrid:
            limit = hybrid.full_text_candidates
        elif source == "graph_search" and graph:
            limit = graph.graph_top_k
        if limit is None:
            limit = request.topk
        selected = [hit for hit in hits if source in hit["sources"]]
        selected.sort(key=lambda hit: hit["score"], reverse=True)
        capped.extend(selected[:limit])

    merged: Dict[Any, Dict[str, Any]] = {}
    for hit in capped:
        key = hit["chunk"]["id"]
        if key in merged:
            merged[key]["sources"] = sorted(set(merged[key]["sources"]) | set(hit["sources"]))
        else:
            merged[key] = dict(hit)
    results = sorted(merged.values(), key=lambda hit: hit["score"], reverse=True)

    # Hybrid caps the combined vector+full-text part; graph is capped above.
    if hybrid and hybrid.hybrid_top_k > 0:
        hybrid_hits = [hit for hit in results
                       if {"vector_search", "full_text_search"} & set(hit["sources"])]
        overflow = {hit["chunk"]["id"] for hit in hybrid_hits[hybrid.hybrid_top_k:]}
        results = [hit for hit in results if hit["chunk"]["id"] not in overflow]

    final = results[: request.topk]
    payload = []
    for hit in final:
        chunk = hit["chunk"]
        item = {
            "id": chunk["id"],
            "score": hit["score"],
            "title": chunk["title"],
            "text": chunk["text"],
            "metadata": {
                **chunk.get("metadata", {}),
                "_search_config": {
                    "search_method": request.search_method,
                    "reranking_enable": request.reranking_enable,
                    "reranking_mode": request.reranking_mode if request.reranking_enable else None,
                },
            },
            "retrieval_source": {"methods": hit["sources"]},
        }
        if request.multi_modal_enable:
            item["chunk_type"] = chunk.get("chunk_type", "text")
            item["file_url"] = chunk.get("file_url", "")
            item["pages"] = chunk.get("pages", [])
        payload.append(item)

    logger.info("SEARCH  query=%r kds=%r method=%s returned=%d",
                request.query, request.kds_list, request.search_method, len(payload))
    return JSONResponse(content={"result": payload, "total_return_count": len(payload)})


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
# Sensitive words
# =============================================================================


class SensitiveWordBusinessError(Exception):
    """AIDP business error returned with an ``error.code`` body."""

    def __init__(self, status_code: int, code: int, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


@app.exception_handler(SensitiveWordBusinessError)
def sensitive_word_business_error(
    _request: StarletteRequest,
    exc: SensitiveWordBusinessError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


def _sensitive_word_error(status_code: int, code: int, message: str) -> SensitiveWordBusinessError:
    """Build an AIDP-style business error.

    AIDP reports duplicate words as HTTP 500 with ``error.code=1022``; the
    mock keeps that shape so the proxy's business-code handling is exercised.
    """
    return SensitiveWordBusinessError(status_code, code, message)


def _public_sensitive_word(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item["id"],
        "word": item["word"],
        "mode": item["mode"],
        "description": item["description"],
        "source": item.get("source", "CUSTOM"),
        "create_time": item.get("create_time", 0),
        "update_time": item.get("update_time", 0),
    }


def _require_sensitive_word_kb(kds_id: str) -> Dict[str, Dict[str, Any]]:
    if kds_id not in _KNOWLEDGE_BASES:
        raise _sensitive_word_error(
            404, 1004, f"Knowledge base {kds_id} not found for sensitive words"
        )
    return _SENSITIVE_WORDS.setdefault(kds_id, {})


def _find_duplicate_word(
    kds_id: str, word: str, mode: str, exclude_id: str | None = None
) -> bool:
    normalized = word.strip().lower()
    return any(
        item["word"].strip().lower() == normalized
        and item["mode"] == mode
        and item["id"] != exclude_id
        for item in _SENSITIVE_WORDS.get(kds_id, {}).values()
    )


@app.get(_SW_PREFIX)
def list_sensitive_words(
    kds_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    keyword: Optional[str] = Query(default=None, max_length=200),
    mode: Optional[Literal["BLACK", "WHITE"]] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    words = _require_sensitive_word_kb(kds_id)
    normalized_keyword = (keyword or "").strip().lower()
    rows = [
        _public_sensitive_word(item)
        for item in words.values()
        if (not normalized_keyword or normalized_keyword in item["word"].lower())
        and (mode is None or item["mode"] == mode)
    ]
    rows.sort(key=lambda item: (item["word"], item["id"]))
    start = (page - 1) * page_size
    total = len(rows)
    # Real AIDP returns a next_link without the active filters; the Nexent
    # client must keep mode/keyword itself instead of following this link.
    next_link = (
        f"{_KB_PREFIX}/{quote(kds_id, safe='')}/SensitiveWords"
        f"?page={page + 1}&page_size={page_size}"
        if page * page_size < total
        else None
    )
    return JSONResponse(
        content={
            "value": rows[start:start + page_size],
            "next_link": next_link,
            "total_count": total,
        }
    )


@app.put(_SW_PREFIX)
def create_sensitive_word(
    kds_id: str,
    body: CreateSensitiveWordBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    words = _require_sensitive_word_kb(kds_id)
    if _find_duplicate_word(kds_id, body.word, body.mode):
        raise _sensitive_word_error(
            500, 1022, "Sensitive word already exists in this knowledge base"
        )
    word_id = f"sw-{uuid.uuid4().hex[:8]}"
    now = int(time.time())
    words[word_id] = {
        "id": word_id,
        "word": body.word,
        "mode": body.mode,
        "description": body.description,
        "source": "CUSTOM",
        "create_time": now,
        "update_time": now,
    }
    _save_state()
    return JSONResponse(status_code=201, content={"id": word_id})


@app.get(f"{_SW_PREFIX}/{{word_id}}")
def get_sensitive_word(
    kds_id: str,
    word_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    words = _require_sensitive_word_kb(kds_id)
    item = words.get(word_id)
    if item is None:
        raise _sensitive_word_error(
            404, 1004, f"Sensitive word {word_id} not found in knowledge base {kds_id}"
        )
    return JSONResponse(content={"data": _public_sensitive_word(item)})


@app.patch(f"{_SW_PREFIX}/{{word_id}}")
def update_sensitive_word(
    kds_id: str,
    word_id: str,
    body: UpdateSensitiveWordBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    words = _require_sensitive_word_kb(kds_id)
    item = words.get(word_id)
    if item is None:
        raise _sensitive_word_error(
            404, 1004, f"Sensitive word {word_id} not found in knowledge base {kds_id}"
        )
    if item.get("source") == "BUILT_IN":
        raise _sensitive_word_error(500, 1008, "Built-in sensitive words are read-only")
    next_word = body.word if body.word is not None else item["word"]
    next_mode = body.mode if body.mode is not None else item["mode"]
    if _find_duplicate_word(kds_id, next_word, next_mode, exclude_id=word_id):
        raise _sensitive_word_error(
            500, 1022, "Sensitive word already exists in this knowledge base"
        )
    item["word"] = next_word
    item["mode"] = next_mode
    if body.description is not None:
        item["description"] = body.description
    item["update_time"] = int(time.time())
    _save_state()
    return JSONResponse(content={})


@app.delete(f"{_SW_PREFIX}/{{word_id}}")
def delete_sensitive_word(
    kds_id: str,
    word_id: str,
    authorization: Optional[str] = Header(default=None),
) -> StarletteResponse:
    _check_auth(authorization)
    words = _require_sensitive_word_kb(kds_id)
    item = words.get(word_id)
    if item is None:
        raise _sensitive_word_error(
            404, 1004, f"Sensitive word {word_id} not found in knowledge base {kds_id}"
        )
    if item.get("source") == "BUILT_IN":
        raise _sensitive_word_error(500, 1008, "Built-in sensitive words are read-only")
    del words[word_id]
    _save_state()
    return StarletteResponse(status_code=204)


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
    _DOCUMENT_PAYLOADS.clear()
    _SENSITIVE_WORDS.clear()
    _seed_initial_data()
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
    _UPLOAD_SECONDS = args.upload_seconds

    EXPECTED_API_KEY = args.api_key

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
