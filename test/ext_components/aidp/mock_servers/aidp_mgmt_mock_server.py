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
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Chunks?file_uuid=  (page a file's chunks)
  - GET    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Chunks/{chunk_id}   (read one chunk)
  - PUT    /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Chunks              (add a chunk)
  - PATCH  /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Chunks/{chunk_id}   (update chunk text)
  - DELETE /KnowledgeBase/Tenants/{tenant}/KnowledgeBases/{id}/Chunks              (remove chunks, JSON body, 204)
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
    and answers every other format with a PDF, reporting the name it served
    in the ``X-File-Name`` header, so a
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

from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
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

# Document chunks, keyed by KB id; each chunk carries the ``file_uuid`` it
# belongs to. Real AIDP derives them while chunking an ingested file, so this
# mock generates a deterministic set per file the first time that file's chunks
# are requested, then stores and mutates exactly like the live service.
_DOCUMENT_CHUNKS_BY_KB: Dict[str, List[Dict[str, Any]]] = {}
# ``"{kds_id}:{file_uuid}"`` entries whose chunks were already generated. Kept
# separately so deleting every chunk is not undone by the next list request.
_DOCUMENT_CHUNK_GENERATED_FILES: set[str] = set()
_NEXT_DOCUMENT_CHUNK_ID: int = 1
_DOCUMENT_CHUNK_TYPES = ("TEXT", "TEXT", "TABLE", "TEXT", "IMAGE")

# Ontology, binding, metadata-definition and chunk state. AIDP owns these
# objects in production; the mock keeps small deterministic fixtures so the
# ontology UI and its proxy can be exercised without a live AIDP deployment.
_ONTOLOGY_DOMAINS: Dict[str, Dict[str, Any]] = {}
_ONTOLOGY_ENTITIES: Dict[str, List[Dict[str, Any]]] = {}
_ONTOLOGY_RELATIONS: Dict[str, List[Dict[str, Any]]] = {}
_ONTOLOGY_BINDINGS: List[Dict[str, Any]] = []
_ONTOLOGY_METADATA: Dict[str, List[Dict[str, str]]] = {}
_ONTOLOGY_RULES: Dict[str, List[Dict[str, Any]]] = {}
_ONTOLOGY_CHUNKS_BY_KB: Dict[str, List[Dict[str, Any]]] = {}

# Deterministic failure knobs for partial-result coverage. They stay in memory
# only so a restart starts from a clean plan, matching the other fault knobs.
_ONTOLOGY_IMPORT_FAIL_API_NAMES: set[str] = set()
_ONTOLOGY_METADATA_FAIL_CHUNK_IDS: set[str] = set()
_ONTOLOGY_ASYNC_THRESHOLD = 200

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


def _seed_ontology_data() -> None:
    """Populate deterministic ontology, binding, metadata and chunk fixtures.

    Two ontology domains are bound to three of the seeded knowledge bases so a
    fresh mock already demonstrates the one-knowledge-base-to-one-domain rule
    and the shared binding count shown on every entity row.
    """
    _ONTOLOGY_DOMAINS.clear()
    _ONTOLOGY_ENTITIES.clear()
    _ONTOLOGY_RELATIONS.clear()
    _ONTOLOGY_BINDINGS.clear()
    _ONTOLOGY_METADATA.clear()
    _ONTOLOGY_RULES.clear()
    _ONTOLOGY_CHUNKS_BY_KB.clear()

    _ONTOLOGY_DOMAINS.update(
        {
            "1": {
                "od_id": 1,
                "name": "电商本体",
                "description": "商品、类目与平台关系的本体示例",
                "metadata_count": 3,
                "entity_count": 4,
                "rule_count": 2,
                "created_by": "李东升",
                "create_time": "2026-01-23",
                "update_time": "2026-01-24",
            },
            "2": {
                "od_id": 2,
                "name": "客服本体",
                "description": "售后与客服问题分类的本体示例",
                "metadata_count": 1,
                "entity_count": 2,
                "rule_count": 1,
                "created_by": "赵晓宇",
                "create_time": "2026-02-10",
                "update_time": "2026-02-12",
            },
        }
    )

    def entity(
        entity_id: str,
        api_name: str,
        display_name: str,
        kind: str,
        description: str,
        *,
        type_id: Optional[str] = None,
        properties: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return {
            "entity_id": entity_id,
            "api_name": api_name,
            "display_name": display_name,
            "description": description,
            "kind": kind,
            "type_id": type_id,
            "properties": properties or [],
            "primary_properties": [item["api_name"] for item in (properties or [])],
            "parent_entities": [],
            "synonym_entities": [],
            "child_entities": [],
            "chunk_count": 0,
            "extended_properties": [],
            "create_time": "2023-01-12 15:30:00",
            "update_time": "2023-01-12 15:30:00",
        }

    _ONTOLOGY_ENTITIES["1"] = [
        entity("101", "Category", "类目", "type", "商品所属的顶层类目"),
        entity("102", "Brand", "品牌", "type", "商品品牌"),
        entity(
            "201",
            "Smartphone",
            "智能手机",
            "entity",
            "在售的智能手机商品",
            type_id="101",
            properties=[
                {"api_name": "price", "display_name": "价格", "value": "3999"},
                {"api_name": "screen_size", "display_name": "屏幕尺寸", "value": "6.1"},
            ],
        ),
        entity(
            "202",
            "Notebook",
            "笔记本电脑",
            "entity",
            "在售的笔记本电脑商品",
            type_id="101",
            properties=[
                {"api_name": "price", "display_name": "价格", "value": "6999"},
            ],
        ),
    ]
    _ONTOLOGY_ENTITIES["1"][0].update(
        {
            "child_entities": ["Smartphone", "Notebook"],
            "chunk_count": 86,
            "extended_properties": [{"key": "业务域", "value": "商品"}],
        }
    )
    _ONTOLOGY_ENTITIES["1"][2].update(
        {
            "parent_entities": ["Category"],
            "synonym_entities": ["Phone"],
            "chunk_count": 120,
            "extended_properties": [{"key": "数据来源", "value": "商品库"}],
        }
    )
    _ONTOLOGY_ENTITIES["1"][3].update(
        {
            "parent_entities": ["Category"],
            "chunk_count": 48,
            "extended_properties": [{"key": "数据来源", "value": "商品库"}],
        }
    )
    _ONTOLOGY_RELATIONS["1"] = [
        {
            "api_name": "belongs_to",
            "display_name": "属于类目",
            "source_api_name": "Smartphone",
            "source_kind": "entity",
            "object_api_name": "Category",
            "object_kind": "type",
            "source_ids": [],
        },
        {
            "api_name": "belongs_to",
            "display_name": "属于类目",
            "source_api_name": "Notebook",
            "source_kind": "entity",
            "object_api_name": "Category",
            "object_kind": "type",
            "source_ids": [],
        },
    ]
    _ONTOLOGY_ENTITIES["2"] = [
        entity("301", "Issue", "问题类型", "type", "客服问题的一级分类"),
        entity(
            "401",
            "RefundRequest",
            "退款申请",
            "entity",
            "用户发起的退款申请",
            type_id="301",
        ),
    ]
    _ONTOLOGY_RELATIONS["2"] = []

    _ONTOLOGY_BINDINGS.extend(
        [
            {
                "id": 1,
                "od_id": 1,
                "kds_id": "14",
                "kb_name": "AIDP FAQ",
            },
            {
                "id": 2,
                "od_id": 1,
                "kds_id": "30",
                "kb_name": "AIDP Product Handbook",
            },
            {
                "id": 3,
                "od_id": 2,
                "kds_id": "31",
                "kb_name": "AIDP API Guide",
            },
        ]
    )

    _ONTOLOGY_METADATA["1"] = [
        {"id": 101, "fieldName": "doc_type", "fieldType": "string", "columnIndex": 1},
        {"id": 102, "fieldName": "publish_year", "fieldType": "number", "columnIndex": 2},
        {"id": 103, "fieldName": "effective_date", "fieldType": "date", "columnIndex": 3},
    ]
    _ONTOLOGY_RULES["1"] = [
        {
            "rule_id": 1,
            "name": "制度文档加分",
            "description": "命中文档类型为制度时提高排序分数",
            "enabled": True,
            "condition": {
                "type": "json",
                "value": {
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "field": "metadata_json.doc_type",
                            "operator": "is",
                            "value": "Policy",
                        }
                    ],
                },
            },
            "action": {
                "type": "json",
                "value": {
                    "effect_mode": "multiply",
                    "coefficient": 0.25,
                },
            },
            "created_at": "2026-03-01 10:00:00",
            "updated_at": "2026-03-05 09:30:00",
        },
        {
            "rule_id": 2,
            "name": "常见问题降权",
            "description": "命中 FAQ 文档时降低排序分数",
            "enabled": False,
            "condition": {
                "type": "json",
                "value": {
                    "logical_operator": "or",
                    "conditions": [
                        {
                            "field": "title",
                            "operator": "contains",
                            "value": "FAQ",
                        },
                        {
                            "field": "chunk_type",
                            "operator": "not_empty",
                            "value": "",
                        },
                    ],
                },
            },
            "action": {
                "type": "json",
                "value": {
                    "effect_mode": "add",
                    "coefficient": -0.1,
                },
            },
            "created_at": "2026-03-02 11:00:00",
            "updated_at": "2026-03-06 15:20:00",
        },
    ]
    _ONTOLOGY_RULES["2"] = [
        {
            "rule_id": 3,
            "name": "客服问题加权",
            "description": "客服问题类型提高排序分数",
            "enabled": True,
            "condition": {
                "type": "json",
                "value": {
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "field": "metadata_json.channel",
                            "operator": "is",
                            "value": "在线",
                        }
                    ],
                },
            },
            "action": {
                "type": "json",
                "value": {
                    "effect_mode": "multiply",
                    "coefficient": 0.15,
                },
            },
            "created_at": "2026-03-03 08:00:00",
            "updated_at": "2026-03-03 08:00:00",
        }
    ]
    _ONTOLOGY_METADATA["2"] = [
        {"id": 201, "fieldName": "channel", "fieldType": "string", "columnIndex": 1},
    ]

    faq_file_uuid = "00000000-0000-4000-8000-000000000001"
    troubleshooting_uuid = "00000000-0000-4000-8000-000000000002"

    def chunk(
        chunk_id: int,
        text_value: str,
        file_name: str,
        file_uuid: str,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_type: str = "TEXT",
        page_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        return {
            "chunk_id": chunk_id,
            "chunk_text": text_value,
            "chunk_type": chunk_type,
            "file_name": file_name,
            "file_url": f"aidp://{file_uuid}",
            "page_ids": page_ids or [],
            "metadata": metadata or {},
            "_file_uuid": file_uuid,
        }

    _ONTOLOGY_CHUNKS_BY_KB["aidp-kb-faq"] = [
        chunk(
            1001,
            "如何在 Nexent 中创建 AIDP 知识库？进入知识库配置页面，点击新建知识库并填写名称、描述与切片参数。",
            "常见问题汇总.txt",
            faq_file_uuid,
            {"doc_type": "FAQ", "publish_year": 2025, "effective_date": "2025-01-01"},
             page_ids=[1],
        ),
        chunk(
            1002,
            "知识库上传文件后可以在上传任务页签中查看处理进度，失败文件支持重试。",
            "常见问题汇总.txt",
            faq_file_uuid,
            {"doc_type": "FAQ", "publish_year": 2025},
        ),
        chunk(
            1003,
            "一个知识库最多绑定一个本体库，一个本体库可以绑定多个知识库。",
            "常见问题汇总.txt",
            faq_file_uuid,
            {},
        ),
        chunk(
            1004,
            "If ingestion fails, inspect the failure reason column and retry the affected files.",
            "troubleshooting.md",
            troubleshooting_uuid,
            {"doc_type": "Guide", "publish_year": 2024},
        ),
        chunk(
            1005,
            "Chunk metadata is displayed in the chunk detail drawer and in retrieval sources.",
            "troubleshooting.md",
            troubleshooting_uuid,
            {},
        ),
    ]


def _save_state() -> None:
    """Atomically persist KB, document, chunk and sensitive-word state to disk.

    Writes to a temporary file and then renames it into place, so a crash
    mid-write cannot corrupt the existing state file. Silently no-ops the
    documents/chunky side of a KB when its document list is missing — only
    KB + document metadata are serialized, not file upload payloads.
    """
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "knowledge_bases": _KNOWLEDGE_BASES,
        "documents_by_kb": _DOCUMENTS_BY_KB,
        "chunks_by_kb": _DOCUMENT_CHUNKS_BY_KB,
        "chunk_generated_files": sorted(_DOCUMENT_CHUNK_GENERATED_FILES),
        "next_chunk_id": _NEXT_DOCUMENT_CHUNK_ID,
        "sensitive_words_by_kb": _SENSITIVE_WORDS,
        "folders_by_kb": _FOLDERS_BY_KB,
        "ontology": {
            "domains": _ONTOLOGY_DOMAINS,
            "entities": _ONTOLOGY_ENTITIES,
            "relations": _ONTOLOGY_RELATIONS,
            "bindings": _ONTOLOGY_BINDINGS,
            "metadata": _ONTOLOGY_METADATA,
            "rules": _ONTOLOGY_RULES,
            "chunks_by_kb": _ONTOLOGY_CHUNKS_BY_KB,
        },
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
    global _NEXT_DOCUMENT_CHUNK_ID
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
            chunk_data = payload.get("chunks_by_kb", {})
            if isinstance(chunk_data, dict):
                _DOCUMENT_CHUNKS_BY_KB.update(chunk_data)
            generated = payload.get("chunk_generated_files", [])
            if isinstance(generated, list):
                _DOCUMENT_CHUNK_GENERATED_FILES.update(
                    item for item in generated if isinstance(item, str)
                )
            next_id = payload.get("next_chunk_id")
            if isinstance(next_id, int) and not isinstance(next_id, bool):
                _NEXT_DOCUMENT_CHUNK_ID = max(_NEXT_DOCUMENT_CHUNK_ID, next_id)
            if isinstance(word_data, dict):
                _SENSITIVE_WORDS.update(word_data)
            if isinstance(folder_data, dict):
                _FOLDERS_BY_KB.update(folder_data)
            for kb in _KNOWLEDGE_BASES.values():
                if isinstance(kb, dict):
                    kb.pop("sensitive_intercept_enalbe", None)
            _seed_sensitive_words_if_empty()
            ontology = payload.get("ontology")
            if isinstance(ontology, dict) and ontology.get("domains"):
                _ONTOLOGY_DOMAINS.update(ontology.get("domains") or {})
                _ONTOLOGY_ENTITIES.update(ontology.get("entities") or {})
                _ONTOLOGY_RELATIONS.update(ontology.get("relations") or {})
                _ONTOLOGY_RULES.update(ontology.get("rules") or {})
                _ONTOLOGY_BINDINGS.extend(ontology.get("bindings") or [])
                for domain in _ONTOLOGY_DOMAINS.values():
                    if isinstance(domain, dict) and domain.get("od_id") is not None:
                        domain["od_id"] = int(domain["od_id"])
                _ONTOLOGY_BINDINGS[:] = [
                    {
                        "id": binding.get("id"),
                        "od_id": int(binding["od_id"]),
                        "kds_id": str(binding["kds_id"]),
                        "kb_name": binding.get("kb_name"),
                        "create_time": binding.get("create_time"),
                    }
                    for binding in _ONTOLOGY_BINDINGS
                    if binding.get("od_id") is not None
                ]
                _ONTOLOGY_METADATA.update(ontology.get("metadata") or {})
                _ONTOLOGY_CHUNKS_BY_KB.update(ontology.get("chunks_by_kb") or {})
            else:
                _seed_ontology_data()
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
    _seed_ontology_data()
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


def _ensure_ontology_chunks() -> None:
    """Bind seeded ontology chunks to the knowledge base's current document UUIDs.

    The demo fixture rewrites ``aidp-kb-faq`` file UUIDs on startup, so chunks
    seeded with the legacy literals would otherwise point at files the file
    list no longer exposes. Keep the first two visible files as the chunk
    sources and let the rest of the fixture stay untouched.
    """
    documents = _active_documents("aidp-kb-faq")
    if len(documents) < 2:
        return
    sources = [documents[0]] * 3 + [documents[1]] * 2
    for index, chunk in enumerate(_ONTOLOGY_CHUNKS_BY_KB.get("aidp-kb-faq", [])):
        if index >= len(sources):
            break
        document = sources[index]
        file_uuid = str(document.get("file_uuid") or "")
        if not file_uuid:
            continue
        chunk["_file_uuid"] = file_uuid
        chunk["file_name"] = document.get("file_name") or chunk.get("file_name")
        chunk["file_url"] = f"aidp://{file_uuid}"


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


def _tree_documents(kds_id: str) -> List[Dict[str, Any]]:
    """Return every file still present in the folder tree.

    Folders/Tree lists files in all HistoryStatus states, not only completed
    ones; rows past their removal window are hidden here while History keeps
    the audit record.
    """
    now = time.time()
    return [
        doc
        for doc in _DOCUMENTS_BY_KB.get(kds_id, [])
        if not (
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
    """Map the mock's task status to AIDP's real HistoryStatus contract 0–7."""
    deleted_at = document.get("_deleted_at")
    if isinstance(deleted_at, (int, float)) and deleted_at > time.time():
        return 6
    if document.get("file_status") == 2:
        return 7
    status = _doc_effective_status(document)
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


def _merge_folder_into(kds_id: str, source: str, destination: str) -> None:
    """Merge one folder subtree into an existing same-named folder.

    Files move into the destination; child folders with a matching name are
    merged recursively, other children keep their names.
    """
    child_folders = sorted(
        path
        for path in _all_folder_paths(kds_id)
        if _folder_parent(path) == source
    )
    for child in child_folders:
        child_name = child.rsplit("/", 1)[-1]
        target_child = f"{destination}/{child_name}"
        if _folder_exists(kds_id, target_child):
            _merge_folder_into(kds_id, child, target_child)
        else:
            _rewrite_folder_prefix(kds_id, child, target_child)
    for document in _DOCUMENTS_BY_KB.get(kds_id, []):
        if not isinstance(document, dict):
            continue
        if (document.get("folder_path") or "/") == source:
            document["folder_path"] = destination
    records = _folder_records(kds_id)
    records[:] = [
        record for record in records if record.get("folder_path") != source
    ]


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
            "summary_enable": bool(kb.get("summary_enable", False)),
            "summary_model": kb.get("summary_model") or "",
            "summary_preview": bool(
                kb.get("summary_preview", kb.get("summary_enable", False))
            ),
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
    result["summary_enable"] = bool(kb.get("summary_enable", False))
    result["summary_model"] = kb.get("summary_model") or ""
    result["summary_preview"] = bool(
        kb.get("summary_preview", result["summary_enable"])
    )
    result["is_exist_graph"] = bool(kb.get("is_exist_graph", False))
    result["is_personal"] = kb.get("is_personal", 0)
    result["state"] = kb.get("state", 4)
    result["role"] = kb.get("role", "Owner")
    result["user_name"] = kb.get("user_name")
    return result


def _same_file_uuid(left: Any, right: Any) -> bool:
    """Compare uuids across the two shapes AIDP deployments report."""
    return _uuid_hex(left) == _uuid_hex(right)


def _find_document(kds_id: str, file_uuid: str) -> Optional[Dict[str, Any]]:
    found = next(
        (
            document
            for document in _DOCUMENTS_BY_KB.get(kds_id, [])
            if _same_file_uuid(document.get("file_uuid"), file_uuid)
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
    if _DOCUMENT_FIXTURE_DIR is not None:
        try:
            fixture_name = f"{uuid.UUID(str(document.get('file_uuid')))}.bin"
        except ValueError:
            fixture_name = None
        if fixture_name:
            fixture = _DOCUMENT_FIXTURE_DIR / fixture_name
            if fixture.is_file():
                return fixture.read_bytes()
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
_PREVIEW_FIXTURE_DIR: Optional[Path] = None
_DOCUMENT_FIXTURE_DIR: Optional[Path] = None


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
    name is what the caller reads from ``X-File-Name``. Explicit local fixtures
    preserve demo content; without them conversion uses a synthetic placeholder.
    """
    filename = str(document.get("file_name") or "document")
    stem, dot, extension = filename.rpartition(".")
    if dot and extension.lower() in _NATIVE_PREVIEW_EXTENSIONS:
        return _document_content(document), filename

    served_name = f"{stem or 'document'}.pdf"
    if _PREVIEW_FIXTURE_DIR is not None:
        # Resolve fixtures by canonical document UUID, never by an uploaded path.
        try:
            fixture_name = f"{uuid.UUID(str(document.get('file_uuid')))}.pdf"
        except ValueError:
            fixture_name = None
        if fixture_name:
            fixture = _PREVIEW_FIXTURE_DIR / fixture_name
            if fixture.is_file():
                content = fixture.read_bytes()
                if content.startswith(b"%PDF-"):
                    return content, served_name
                raise ValueError("Preview fixture is not a PDF")
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
    summary_enable: bool = False
    summary_model: Optional[str] = None
    summary_preview: Optional[bool] = None
    sensitive_intercept_enable: int = 0


class UpdateKbBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    summary_enable: Optional[bool] = None
    summary_model: Optional[str] = None
    summary_preview: Optional[bool] = None
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
    # Present values mirror the real AIDP contract (1-100); omission means
    # "no separate cap", which the mock evaluates as falling back to topk.
    hybrid_top_k: Optional[int] = Field(None, ge=1, le=100)
    vector_score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    full_text_score_threshold: float = Field(0.0, ge=0.0, le=1.0)


class GraphSearchConfig(BaseModel):
    """Per-channel knobs for the graph part of a FusionSearch call."""

    graph_top_k: Optional[int] = Field(None, ge=1, le=100)
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
    ontology_enhance_enable: bool = False
    rule_enable: bool = False

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
        # Compute effective caps the way AIDP fills omitted values.
        h = self.hybrid_search_config.hybrid_top_k if self.hybrid_search_config else None
        g = self.graph_search_config.graph_top_k if self.graph_search_config else None
        effective_g = g if g is not None else min(5, self.topk)
        effective_h = h if h is not None else self.topk - effective_g
        if hybrid and h is not None and h > self.topk:
            raise ValueError("hybrid_top_k must not exceed topk")
        if graph and g is not None and g > self.topk:
            raise ValueError("graph_top_k must not exceed topk")
        if hybrid and graph and effective_h + effective_g > self.topk:
            raise ValueError("hybrid_top_k + graph_top_k must not exceed topk")
        if hybrid and h is not None:
            if "vector_search" in channels and self.hybrid_search_config.vector_candidates < h:
                raise ValueError("vector_candidates must be at least hybrid_top_k")
            if "full_text_search" in channels and self.hybrid_search_config.full_text_candidates < h:
                raise ValueError("full_text_candidates must be at least hybrid_top_k")
        return self


class RemoveFilesBody(BaseModel):
    file_uuids: List[str] = Field(..., min_length=1)


class CountFilesBody(BaseModel):
    """Body of POST .../KnowledgeFiles/Count (all fields optional)."""

    fs_id: Optional[str] = None
    dir_path: Optional[str] = None
    keyword: Optional[str] = Field(default=None, max_length=200)


class DownloadFileBody(BaseModel):
    file_uuid: uuid.UUID = Field(...)


class CreateChunkBody(BaseModel):
    """Body of PUT .../Chunks (add one chunk to a file)."""

    file_uuid: uuid.UUID = Field(...)
    chunk_text: str = Field(..., min_length=1, max_length=10240)


class UpdateChunkBody(BaseModel):
    """Body of PATCH .../Chunks/{chunk_id} (text is the only writable field)."""

    chunk_text: str = Field(..., min_length=1, max_length=10240)


class SummaryStatusBody(BaseModel):
    """Body of POST /_mock/summary-status."""

    kds_id: str
    file_uuid: uuid.UUID
    status: Literal["pending", "success", "failed"]
    summary_text: Optional[str] = None


class FileSummaryBody(BaseModel):
    """Body of POST .../KnowledgeFiles/Summary (2026-11-25 contract)."""

    file_uuid: uuid.UUID


class RemoveChunksBody(BaseModel):
    """Body of DELETE .../Chunks."""

    chunk_ids: List[int] = Field(..., min_length=1, max_length=2000)

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

# Bind ontology chunk fixtures to the document UUIDs the demo fixture settled
# on. This runs after every helper it needs is defined, still before the first
# request can be served.
_ensure_ontology_chunks()
_save_state()


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

    if body.summary_enable and not (body.summary_model or "").strip():
        raise HTTPException(
            status_code=400,
            detail="summary_model is required when summary_enable is true",
        )
    # The live service rejects a duplicate name with HTTP 500 and business
    # code 1022 (not a 4xx). Mirror that shape so the proxy's error parsing
    # and the UI's duplicate-name message are exercised realistically.
    if any(kb["kds_name"] == body.name for kb in _KNOWLEDGE_BASES.values()):
        logger.info("CREATE REJECTED duplicate name=%r", body.name)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 1022,
                    "message": "Create knowledge base failed",
                }
            },
        )

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
    new_kb["summary_enable"] = body.summary_enable
    new_kb["summary_model"] = (
        body.summary_model.strip() if body.summary_enable and body.summary_model else ""
    )
    new_kb["summary_preview"] = (
        body.summary_preview if body.summary_preview is not None else body.summary_enable
    )

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
    binding = next(
        (row for row in _ONTOLOGY_BINDINGS if row.get("kds_id") == kds_id),
        None,
    )
    if binding:
        domain = _ONTOLOGY_DOMAINS.get(str(binding["od_id"])) or {}
        result["bind_lib_id"] = binding["od_id"]
        result["bind_lib_type"] = "ontology"
        result["bind_lib_name"] = domain.get("name") or ""
    else:
        result["bind_lib_id"] = 0
        result["bind_lib_type"] = "none"
        result["bind_lib_name"] = ""

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
    if body.summary_enable is not None:
        if body.summary_enable and not (body.summary_model or "").strip():
            raise HTTPException(
                400, "summary_model is required when summary_enable is true"
            )
        kb["summary_enable"] = body.summary_enable
        kb["summary_model"] = (
            body.summary_model.strip() if body.summary_enable and body.summary_model else ""
        )
        kb["summary_preview"] = (
            body.summary_preview
            if body.summary_preview is not None
            else body.summary_enable
        )
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


def _name_conflict(path: str, *, code: int = 1089) -> HTTPException:
    """AIDP 1089 for file/folder duplicates; 1092 for folder-move duplicates."""
    message = (
        f"folder already exists at target: {path}"
        if code == 1092
        else f"name already exists: {path}"
    )
    return HTTPException(status_code=409, detail={"code": code, "message": message})


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
            for document in _tree_documents(kds_id)
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
    if destination in _all_folder_paths(kds_id):
        if not body.merge_on_conflict:
            raise _name_conflict(destination, code=1092)
        _merge_folder_into(kds_id, source, destination)
    else:
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
            (
                document
                for document in documents
                if _same_file_uuid(document.get("file_uuid"), file_uuid)
            ),
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
# Document chunks (semantic slicing)
# =============================================================================
def _public_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """Return chunk fields without any mock-only private keys."""
    return {key: value for key, value in chunk.items() if not key.startswith("_")}


def _file_chunks(kds_id: str, file_uuid: str) -> List[Dict[str, Any]]:
    return [
        chunk
        for chunk in _DOCUMENT_CHUNKS_BY_KB.get(kds_id, [])
        if _same_file_uuid(chunk.get("file_uuid"), file_uuid)
    ]


def _next_chunk_id() -> int:
    global _NEXT_DOCUMENT_CHUNK_ID
    chunk_id = _NEXT_DOCUMENT_CHUNK_ID
    _NEXT_DOCUMENT_CHUNK_ID += 1
    return chunk_id


def _ensure_file_chunks(kds_id: str, document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate a deterministic chunk set for a file the first time it is read.

    Real AIDP chunks each ingested file; the mock has no parser, so it writes a
    fixed set once and then treats it like user data (edits and removals stick,
    including deleting every chunk).
    """
    file_uuid = str(document.get("file_uuid"))
    marker = f"{kds_id}:{file_uuid}"
    if marker in _DOCUMENT_CHUNK_GENERATED_FILES:
        return _file_chunks(kds_id, file_uuid)

    file_name = str(document.get("file_name") or "document")
    stubs = [
        ("这是文件的标题与概述部分，用于验证语义切片的查看与编辑。", [1]),
        ("第二段正文示例：AIDP 在入库时按语义边界切分文本，每个切片带有页码与元数据。", [1]),
        ("核心指标对照\n\n<table><thead><tr><th>指标</th><th>取值</th><th>说明</th></tr></thead><tbody><tr><td>准确率</td><td>98%</td><td>测试集结果</td></tr><tr><td>召回率</td><td>95%</td><td>测试集结果</td></tr></tbody></table>", [2]),
        ("第三段正文示例：切片的文本可在此页面修改，修改只提交 chunk_text 字段。", [2, 3]),
        ("图片说明示例：该切片对应文档中的插图说明文字。", [3]),
    ]
    chunks = _DOCUMENT_CHUNKS_BY_KB.setdefault(kds_id, [])
    for index, (text, pages) in enumerate(stubs):
        chunk_type = _DOCUMENT_CHUNK_TYPES[index % len(_DOCUMENT_CHUNK_TYPES)]
        if chunk_type == "IMAGE":
            # Real AIDP stores each image chunk's picture under
            # "{kds_id}/{file_ino_no}/{image_uuid}.png" served through
            # ViewImage; text/table chunks report the literal "null".
            image_file_url = f"{kds_id}/{document.get('file_ino_no')}/{uuid.uuid4()}.png"
        else:
            image_file_url = "null"
        chunk = {
            "chunk_id": _next_chunk_id(),
            "chunk_text": text,
            "chunk_type": chunk_type,
            "file_uuid": file_uuid,
            "file_name": file_name,
            "file_url": image_file_url,
            "page_ids": pages,
            "metadata": {"section": f"part-{index + 1}", "source": file_name},
            "metadata_json": {},
        }
        # User-defined metadata from the bound ontology domain; the page shows
        # this field instead of AIDP's system metadata. Keys mirror domain 1's
        # definitions so the FAQ demo KB (bound to domain 1) round-trips them.
        if index in (0, 4):
            chunk["metadata_json"] = {"doc_type": "faq", "publish_year": "2026"}
        # Newer AIDP builds return ontology auto-tags on `tag`; only some
        # chunks carry them, so the page must treat the field as optional.
        if index in (0, 2):
            chunk["tag"] = ["智能手机"]
        chunks.append(chunk)
    _DOCUMENT_CHUNK_GENERATED_FILES.add(marker)
    _save_state()
    return _file_chunks(kds_id, file_uuid)


def _require_file(kds_id: str, file_uuid: str) -> Dict[str, Any]:
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    document = _find_document(kds_id, file_uuid)
    if document is None:
        raise HTTPException(status_code=404, detail=f"File {file_uuid} not found")
    return document


def _require_chunk(kds_id: str, chunk_id: int) -> Dict[str, Any]:
    chunk = next(
        (
            item
            for item in _DOCUMENT_CHUNKS_BY_KB.get(kds_id, [])
            if item.get("chunk_id") == chunk_id
        ),
        None,
    )
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")
    return chunk


@app.get(f"{_KB_PREFIX}/{{kds_id}}/Chunks")
def list_chunks(
    kds_id: str,
    file_uuid: uuid.UUID = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Page through the chunks of one file, as the live contract declares."""
    _check_auth(authorization)
    document = _require_file(kds_id, str(file_uuid))
    chunks = _ensure_file_chunks(kds_id, document)
    start = (page - 1) * page_size
    items = [_public_chunk(chunk) for chunk in chunks[start:start + page_size]]
    # The current contract sends next_link=null on the last page.
    has_next = page * page_size < len(chunks)
    next_link = None
    if has_next:
        next_link = (
            f"{_KB_PREFIX}/{kds_id}/Chunks?file_uuid={file_uuid}"
            f"&page={page + 1}&page_size={page_size}"
        )
    logger.info(
        "LIST CHUNKS  kds_id=%s file=%s page=%d returned=%d total=%d",
        kds_id, file_uuid, page, len(items), len(chunks),
    )
    return JSONResponse(content={
        "value": items,
        "next_link": next_link,
        "total_count": len(chunks),
    })


@app.put(f"{_KB_PREFIX}/{{kds_id}}/Chunks")
def create_chunk(
    kds_id: str,
    body: CreateChunkBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Add one chunk and answer with its id, as the live service does."""
    _check_auth(authorization)
    document = _require_file(kds_id, str(body.file_uuid))
    if not body.chunk_text.strip():
        raise HTTPException(status_code=400, detail="chunk_text must not be blank")
    chunk = {
        "chunk_id": _next_chunk_id(),
        "chunk_text": body.chunk_text,
        "chunk_type": "TEXT",
        "file_uuid": str(body.file_uuid),
        "file_name": str(document.get("file_name") or ""),
        "file_url": f"/aidp/knowledge/{kds_id}/{document.get('file_name') or ''}",
        "page_ids": [],
        "metadata": {},
    }
    _DOCUMENT_CHUNKS_BY_KB.setdefault(kds_id, []).append(chunk)
    _DOCUMENT_CHUNK_GENERATED_FILES.add(f"{kds_id}:{body.file_uuid}")
    _save_state()
    return JSONResponse(content={"chunk_id": str(chunk["chunk_id"])})


@app.post(f"{_KB_PREFIX}/{{kds_id}}/Chunks/Remove")
def remove_chunks(
    kds_id: str,
    body: RemoveChunksBody,
    authorization: Optional[str] = Header(default=None),
) -> Response:
    """Remove the requested chunks; the live contract answers 204 with no body.

    The 2026-11-20 verified contract uses POST /Chunks/Remove; the earlier
    DELETE /Chunks variant is not served by the real deployment (405).
    """
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    targets = set(body.chunk_ids)
    _DOCUMENT_CHUNKS_BY_KB[kds_id] = [
        chunk
        for chunk in _DOCUMENT_CHUNKS_BY_KB.get(kds_id, [])
        if chunk.get("chunk_id") not in targets
    ]
    _save_state()
    return Response(status_code=204)


def _mock_png_bytes() -> bytes:
    """Build a tiny solid-colour PNG without third-party imaging libraries."""
    import struct
    import zlib

    width = height = 96
    red, green, blue = 0x00, 0x67, 0xD1

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanline = b"\x00" + bytes([red, green, blue]) * width
    idat = zlib.compress(scanline * height)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


@app.get(f"{_KB_PREFIX}/{{kds_id}}/ViewImage/{{file_id}}")
def view_image(
    kds_id: str,
    file_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Response:
    """Serve a chunk image as PNG bytes, mirroring the live ViewImage contract.

    The real service derives ``file_id`` from a chunk's ``file_url``
    (``{kds_id}/{file_ino_no}/{image_uuid}.png`` -> ``{file_ino_no}_
    {image_uuid}.png``); the mock accepts any well-formed id from this KB.
    """
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", file_id):
        raise HTTPException(status_code=400, detail="Invalid FileID format")
    # Demo fixtures may hold the real picture bytes under the image uuid; a
    # seeded demo otherwise falls back to the synthetic PNG.
    if _DOCUMENT_FIXTURE_DIR is not None:
        image_uuid = file_id.rsplit("_", 1)[-1].removesuffix(".png")
        try:
            fixture = _DOCUMENT_FIXTURE_DIR / f"{uuid.UUID(image_uuid)}.bin"
        except ValueError:
            fixture = None
        if fixture is not None and fixture.is_file():
            content = fixture.read_bytes()
            media_type = "image/png"
            if content.startswith(bytes([0xFF, 0xD8])):
                media_type = "image/jpeg"
            elif content.startswith(b"BM"):
                media_type = "image/bmp"
            return Response(content=content, media_type=media_type)
    return Response(content=_mock_png_bytes(), media_type="image/png")


@app.patch(f"{_KB_PREFIX}/{{kds_id}}/Chunks/BatchMetadataJson")
def batch_chunk_metadata(
    kds_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Apply metadata/tags to chunks selected by ids or by file UUIDs.

    Registered before the ``/Chunks/{chunk_id}`` template so the literal
    ``BatchMetadataJson`` path is not captured as a chunk id.
    """
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    raw_od_id = body.get("od_id")
    if not isinstance(raw_od_id, int) or isinstance(raw_od_id, bool):
        raise HTTPException(status_code=400, detail="od_id must be an integer")
    od_id = raw_od_id
    metadata = body.get("metadata_json")
    tag = body.get("tag")
    chunk_ids = body.get("chunk_id_list") or []
    file_uuids = {str(item) for item in (body.get("file_uuid_list") or [])}
    if metadata is None and tag is None:
        raise HTTPException(
            status_code=400,
            detail="one of metadata_json or tag is required",
        )
    if not any(
        binding["od_id"] == od_id and binding["kds_id"] == kds_id
        for binding in _ONTOLOGY_BINDINGS
    ):
        raise HTTPException(
            status_code=400,
            detail="Knowledge base is not bound to the ontology domain",
        )
    defined = {
        item["fieldName"] for item in _ONTOLOGY_METADATA.get(str(od_id), [])
    }
    if metadata is not None:
        if not isinstance(metadata, dict) or not metadata:
            raise HTTPException(
                status_code=400,
                detail="metadata_json must not be empty",
            )
        if not set(metadata).issubset(defined):
            raise HTTPException(
                status_code=400,
                detail="metadata_json contains undefined fields",
            )
    if tag is not None and (
        not isinstance(tag, list)
        or any(not isinstance(item, str) or not item.strip() for item in tag)
    ):
        raise HTTPException(
            status_code=400,
            detail="tag must be a list of non-empty strings",
        )

    id_targets = {
        item if isinstance(item, int) else int(item)
        for item in chunk_ids
        if isinstance(item, int) or str(item).isdigit()
    }
    success = 0
    failed = 0
    for chunk in _DOCUMENT_CHUNKS_BY_KB.get(kds_id, []):
        if chunk.get("chunk_id") not in id_targets and not any(
            _same_file_uuid(chunk.get("file_uuid"), target)
            for target in file_uuids
        ):
            continue
        if str(chunk.get("chunk_id")) in _ONTOLOGY_METADATA_FAIL_CHUNK_IDS:
            failed += 1
            continue
        if metadata is not None:
            target = chunk.setdefault("metadata_json", {})
            for key, value in metadata.items():
                if value is None:
                    target.pop(key, None)
                else:
                    target[key] = str(value)
        if tag is not None:
            chunk["tag"] = list(tag)
        success += 1
    _save_state()
    return {
        "kds_id": kds_id,
        "od_id": str(od_id),
        "partial_failure": failed > 0,
        "total_chunks": success + failed,
        "updated_chunks": success,
    }


@app.get(f"{_KB_PREFIX}/{{kds_id}}/Chunks/{{chunk_id}}")
def get_chunk(
    kds_id: str,
    chunk_id: int,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Read one chunk."""
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    return JSONResponse(content=_public_chunk(_require_chunk(kds_id, chunk_id)))


@app.patch(f"{_KB_PREFIX}/{{kds_id}}/Chunks/{{chunk_id}}")
def update_chunk(
    kds_id: str,
    chunk_id: int,
    body: UpdateChunkBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Update one chunk's text."""
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    chunk = _require_chunk(kds_id, chunk_id)
    if not body.chunk_text.strip():
        raise HTTPException(status_code=400, detail="chunk_text must not be blank")
    chunk["chunk_text"] = body.chunk_text
    _save_state()
    return JSONResponse(content=_public_chunk(chunk))

# =============================================================================
# Ingestion channels + knowledge-file history
# =============================================================================



# =============================================================================
# File summaries
# =============================================================================
def _summary_preview_enabled(kb: Dict[str, Any]) -> bool:
    return bool(kb.get("summary_enable")) and bool(
        kb.get("summary_preview", kb.get("summary_enable"))
    )


def _ensure_summary_state(kb: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
    """Give a file a deterministic summary the first time it is requested."""
    status = document.get("_summary_status")
    if status not in {"pending", "success", "failed"}:
        document["_summary_status"] = "success"
        document["_summary_text"] = (
            f"{document.get('file_name', '文件')} 的摘要："
            f"该摘要由 Mock 按知识库配置生成，模型为 {kb.get('summary_model') or '-'}。"
        )
    return document


@app.post(f"{_KB_PREFIX}/{{kds_id}}/KnowledgeFiles/Summary")
def get_file_summary(
    kds_id: str,
    body: FileSummaryBody,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Read one file summary; preview disabled returns an empty object."""
    _check_auth(authorization)
    kb = _KNOWLEDGE_BASES.get(kds_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kds_id} not found")
    document = _find_document(kds_id, str(body.file_uuid))
    if document is None:
        raise HTTPException(status_code=404, detail=f"File {body.file_uuid} not found")
    if not _summary_preview_enabled(kb):
        return JSONResponse(content={})
    document = _ensure_summary_state(kb, document)
    _save_state()
    result = {
        "summary_status": document.get("_summary_status"),
        "summary_model": kb.get("summary_model") or "",
    }
    if result["summary_status"] == "success":
        result["summary_text"] = document.get("_summary_text") or ""
    elif result["summary_status"] == "failed":
        result["error_reason"] = (
            document.get("_summary_error_reason")
            or "llm_failed: mock summary generation failed"
        )
    return JSONResponse(content=result)


@app.post("/_mock/summary-status")
def set_summary_status(body: SummaryStatusBody) -> JSONResponse:
    """Test control: force one file summary into any state."""
    kb = _KNOWLEDGE_BASES.get(body.kds_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base {body.kds_id} not found")
    document = _find_document(body.kds_id, str(body.file_uuid))
    if document is None:
        raise HTTPException(status_code=404, detail=f"File {body.file_uuid} not found")
    document["_summary_status"] = body.status
    if body.summary_text is not None:
        document["_summary_text"] = body.summary_text
    elif body.status != "success":
        document["_summary_text"] = ""
    _save_state()
    return JSONResponse(content={
        "kds_id": body.kds_id,
        "file_uuid": str(body.file_uuid),
        "status": body.status,
    })


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
            "chunk_type": "TEXT",
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


def _metadata_value(chunk: Dict[str, Any], field: str) -> str:
    """Read a filterable field, falling back to the chunk title for file names.

    Real AIDP stores ``original_file_name`` with the file identity; the static
    chunk fixtures only carry a title, so the title is the local equivalent.
    """
    value = str(chunk.get("metadata", {}).get(field, ""))
    if not value and field in ("original_file_name", "file_name"):
        value = str(chunk.get("title") or "")
    return value


def _chunks_for_kb(kds_id: str) -> List[Dict[str, Any]]:
    """Return the KB's searchable chunks.

    Static fixtures cover the seed KBs. KBs created or imported at runtime (the
    file-scope demo KBs) only exist in the state documents, so synthesize one
    searchable chunk per active document. The synthesized chunk carries
    ``original_file_name`` so the conversation metadata filter can be exercised
    locally the same way the real service applies it.
    """
    chunks = _CHUNKS_BY_KB.get(kds_id)
    if chunks:
        return chunks
    synthetic: List[Dict[str, Any]] = []
    id_base = 900000 + (sum(ord(char) for char in kds_id) % 1000) * 100
    for index, document in enumerate(_active_documents(kds_id)):
        name = str(document.get("file_name") or "").strip()
        if not name:
            continue
        synthetic.append({
            "id": id_base + index,
            "score": round(0.9 - index * 0.001, 4),
            "title": name,
            "text": f"{name} local mock content for metadata-filter verification.",
            "metadata": {
                "original_file_name": name,
                "knowledge_base_id": kds_id,
            },
            "chunk_type": "text",
            "file_url": "",
            "pages": [1],
            "retrieval_sources": ["vector_search", "full_text_search"],
        })
    return synthetic


def _match_metadata(chunk: Dict[str, Any], condition: Optional[MetadataCondition]) -> bool:
    if not condition or not condition.conditions:
        return True
    results = []
    for c in condition.conditions:
        field = c.get("name", "")
        op = c.get("comparison_operator", "contains")
        val = c.get("value", "")
        cv = _metadata_value(chunk, field)
        lowered_cv = cv.lower()
        lowered_val = str(val).lower()
        if op == "contains":
            results.append(lowered_val in lowered_cv)
        elif op in ("equals", "is", "="):
            results.append(lowered_cv == lowered_val)
        elif op in ("not_equals", "is not"):
            results.append(lowered_cv != lowered_val)
        elif op == "start with":
            results.append(lowered_cv.startswith(lowered_val))
        elif op == "end with":
            results.append(lowered_cv.endswith(lowered_val))
        elif op == "not contains":
            results.append(lowered_val not in lowered_cv)
        elif op == "empty":
            results.append(cv in ("", "None"))
        elif op == "not_empty":
            results.append(cv not in ("", "None"))
        else:
            results.append(False)
    return all(results) if condition.logical_operator == "and" else any(results)


def _retrieval_chunks_for_kb(kb_id: str) -> List[Dict[str, Any]]:
    """Use seeded retrieval fixtures, or adapt uploaded document chunks.

    The management mock owns the chunks created through the Chunk CRUD
    endpoints; FusionSearch needs the same data for local demos.
    """
    static_chunks = _CHUNKS_BY_KB.get(kb_id)
    if static_chunks:
        return static_chunks
    chunks = []
    for chunk in _DOCUMENT_CHUNKS_BY_KB.get(kb_id, []):
        chunks.append({
            "id": chunk.get("chunk_id"),
            "score": 0.8,
            "title": chunk.get("file_name", ""),
            "text": chunk.get("chunk_text", ""),
            "metadata": chunk.get("metadata", {}),
            "chunk_type": chunk.get("chunk_type", "TEXT"),
            "file_url": chunk.get("file_url", ""),
            "pages": chunk.get("page_ids", []),
            "retrieval_sources": ["vector_search", "full_text_search"],
            "_search_dynamic": True,
        })
    return chunks

_LAST_FUSION_REQUEST: Optional[Dict[str, Any]] = None


@app.get("/_mock/last-fusion-search")
def get_last_fusion_search() -> JSONResponse:
    """Expose the last accepted FusionSearch body for request-shape checks."""
    return JSONResponse(content={"request": _LAST_FUSION_REQUEST})


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
    global _LAST_FUSION_REQUEST
    _LAST_FUSION_REQUEST = request.model_dump()

    channels = set(_RETRIEVAL_CHANNELS if request.search_method == "hybrid_search"
                   else request.search_method.split("|"))
    hybrid = request.hybrid_search_config
    graph = request.graph_search_config
    query_terms = [t.strip().lower() for t in request.query.split() if t.strip()]
    hits: List[Dict[str, Any]] = []

    for kb_id in request.kds_list:
        kb = _KNOWLEDGE_BASES.get(kb_id, {})
        graph_available = bool(kb.get("is_exist_graph"))
        source_chunks = _retrieval_chunks_for_kb(kb_id) or _chunks_for_kb(kb_id)
        for chunk in source_chunks:
            if not _match_metadata(chunk, request.metadata_condition):
                continue
            if not request.multi_modal_enable and chunk.get("chunk_type") == "image":
                continue

            haystack = f"{chunk.get('title', '')} {chunk.get('text', '')}".lower()
            if (
                chunk.get("_search_dynamic")
                and query_terms
                and not any(term in haystack for term in query_terms)
            ):
                continue
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
            limit = graph.graph_top_k if graph.graph_top_k is not None else min(5, request.topk)
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
    if hybrid:
        effective_g = graph.graph_top_k if graph and graph.graph_top_k is not None else min(5, request.topk)
        effective_h = hybrid.hybrid_top_k if hybrid.hybrid_top_k is not None else request.topk - effective_g
        hybrid_hits = [hit for hit in results
                       if {"vector_search", "full_text_search"} & set(hit["sources"])]
        overflow = {hit["chunk"]["id"] for hit in hybrid_hits[effective_h:]}
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

    logger.info("SEARCH  query=%r kds=%r metadata=%r method=%s returned=%d",
                request.query, request.kds_list,
                (request.metadata_condition.model_dump(exclude_none=True)
                 if request.metadata_condition is not None else None),
                request.search_method, len(payload))
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
# Ontology, binding, metadata definition and chunk endpoints
# =============================================================================

_ONTOLOGY_PREFIX = f"/KnowledgeBase/Tenants/{TENANT}/OntologyDomain"
_ONTOLOGY_PLURAL_PREFIX = f"/KnowledgeBase/Tenants/{TENANT}/OntologyDomains"


def _ontology_domain_or_404(domain_id: str) -> Dict[str, Any]:
    domain = _ONTOLOGY_DOMAINS.get(str(domain_id))
    if domain is None:
        raise HTTPException(status_code=404, detail="Ontology domain not found")
    return domain


def _next_numeric_id(values: List[Any], prefix: int = 0) -> str:
    numeric = [int(value) for value in values if str(value).isdigit()]
    return str(max(numeric, default=prefix) + 1)


def _public_entity(item: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


_TAG_SYNC_TASK_SEQ = 1000


@app.post(f"{_ONTOLOGY_PREFIX}/TagSync")
def sync_ontology_tags(
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Queue one ontology auto-tagging task for the given numeric KB ids."""
    _check_auth(authorization)
    kb_ids = body.get("kb_ids")
    if (
        not isinstance(kb_ids, list)
        or not kb_ids
        or any(not isinstance(item, int) or isinstance(item, bool) for item in kb_ids)
    ):
        raise HTTPException(status_code=400, detail="kb_ids must be a non-empty integer list")
    global _TAG_SYNC_TASK_SEQ
    _TAG_SYNC_TASK_SEQ += 1
    return JSONResponse(
        content={"task_id": _TAG_SYNC_TASK_SEQ, "task_type": "ontology_auto_extract"}
    )


@app.get(_ONTOLOGY_PREFIX)
def list_ontology_domains(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    items = list(_ONTOLOGY_DOMAINS.values())
    if search and search.strip():
        needle = search.strip().lower()
        # The confirmed UI only promises name search; AIDP has not confirmed
        # whether description participates.
        items = [
            item
            for item in items
            if needle in str(item.get("name", "")).lower()
        ]
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start:start + page_size]
    next_link = (
        f"{_ONTOLOGY_PREFIX}?page={page + 1}&page_size={page_size}"
        if start + page_size < total
        else None
    )
    return {"value": page_items, "total_count": total, "next_link": next_link}


@app.put(_ONTOLOGY_PREFIX)
def create_ontology_domain(
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    domain_id = _next_numeric_id(list(_ONTOLOGY_DOMAINS))
    record = {
        "od_id": int(domain_id),
        "name": name,
        "description": str(body.get("description") or ""),
        "metadata_count": 0,
        "entity_count": 0,
        "created_by": "演示用户",
        "create_time": int(time.time()),
        "update_time": int(time.time()),
    }
    _ONTOLOGY_DOMAINS[domain_id] = record
    _ONTOLOGY_ENTITIES.setdefault(domain_id, [])
    _ONTOLOGY_RELATIONS.setdefault(domain_id, [])
    _ONTOLOGY_METADATA.setdefault(domain_id, [])
    _save_state()
    return JSONResponse(
        status_code=201,
        content={
            "domain_id": int(domain_id),
            "message": "create ontology domain success",
        },
    )


# Bindings are registered before /OntologyDomain/{domain_id} so the static
# segment is not captured as a domain id.
# Confirmed Bindings contract: create under OntologyDomain (singular), list
# under OntologyDomains/{DomainId} (plural), delete by BindingId.
@app.put(f"{_ONTOLOGY_PREFIX}/Bindings")
def create_ontology_binding_confirmed(
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    raw_domain_id = body.get("domain_id", body.get("od_id"))
    try:
        domain_id = int(raw_domain_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="domain_id must be an integer")
    kds_id = str(body.get("kb_id") or body.get("kds_id") or "")
    if str(domain_id) not in _ONTOLOGY_DOMAINS:
        raise HTTPException(status_code=404, detail="Ontology domain not found")
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    for binding in _ONTOLOGY_BINDINGS:
        if binding["kds_id"] != kds_id:
            continue
        if binding["od_id"] == domain_id:
            return binding
        raise HTTPException(
            status_code=409,
            detail="ONTOLOGY_KDS_BIND_CONFLICT(1055): knowledge base is already bound or unbinding",
        )
    binding = {
        "id": max([int(item.get("id") or 0) for item in _ONTOLOGY_BINDINGS] or [0]) + 1,
        "od_id": domain_id,
        "kds_id": kds_id,
        "kb_name": (_KNOWLEDGE_BASES.get(kds_id) or {}).get("kds_name"),
        "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _ONTOLOGY_BINDINGS.append(binding)
    _save_state()
    return {"id": binding["id"], "kb_id": kds_id, "domain_id": domain_id}


@app.get(f"{_ONTOLOGY_PLURAL_PREFIX}/{{domain_id}}/Bindings")
def list_domain_bindings_confirmed(
    domain_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    rows = [
        binding
        for binding in _ONTOLOGY_BINDINGS
        if binding["od_id"] == int(domain_id)
    ]
    total = len(rows)
    start = (page - 1) * page_size
    items = [
        {
            # The real example omits BindingId; the demo keeps it so unbind can
            # be demonstrated, and the UI labels that difference in red.
            "id": row.get("id"),
            "kb_id": row["kds_id"],
            "kb_name": row.get("kb_name"),
            "domain_id": row["od_id"],
            "domain_name": (_ONTOLOGY_DOMAINS.get(str(row["od_id"])) or {}).get("name"),
            "create_time": row.get("create_time"),
        }
        for row in rows[start:start + page_size]
    ]
    next_link = (
        f"{_ONTOLOGY_PLURAL_PREFIX}/{domain_id}/Bindings?page={page + 1}&page_size={page_size}"
        if start + page_size < total
        else None
    )
    return {"data": {"items": items, "total_count": total, "next_link": next_link}}


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Bindings")
def list_domain_bindings_singular(
    domain_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Per-domain bindings on the singular route the proxy pages through."""
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    rows = [
        binding
        for binding in _ONTOLOGY_BINDINGS
        if binding["od_id"] == int(domain_id)
    ]
    total = len(rows)
    start = (page - 1) * page_size
    items = [
        {
            "kb_id": row["kds_id"],
            "kb_name": row.get("kb_name"),
            "domain_id": row["od_id"],
            "create_time": row.get("create_time"),
        }
        for row in rows[start : start + page_size]
    ]
    next_link = (
        f"{_ONTOLOGY_PREFIX}/{domain_id}/Bindings?page={page + 1}&page_size={page_size}"
        if start + page_size < total
        else None
    )
    return {"value": items, "total_count": total, "next_link": next_link}


@app.delete(f"{_ONTOLOGY_PREFIX}/Bindings/{{binding_id}}")
def delete_ontology_binding_confirmed(
    binding_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    before = len(_ONTOLOGY_BINDINGS)
    _ONTOLOGY_BINDINGS[:] = [
        binding
        for binding in _ONTOLOGY_BINDINGS
        if str(binding.get("id")) != str(binding_id)
    ]
    if len(_ONTOLOGY_BINDINGS) == before:
        raise HTTPException(status_code=404, detail="Binding not found")
    _save_state()
    return JSONResponse(status_code=200, content={"data": None})


@app.get(f"{_ONTOLOGY_PREFIX}/Bindings")
def list_ontology_bindings(
    od_id: Optional[int] = Query(default=None),
    kds_id: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    rows = [
        binding
        for binding in _ONTOLOGY_BINDINGS
        if (od_id is None or binding["od_id"] == od_id)
        and (kds_id is None or binding["kds_id"] == str(kds_id))
    ]
    return {"value": rows, "total_count": len(rows), "next_link": None}


@app.post(f"{_ONTOLOGY_PREFIX}/Bindings")
def create_ontology_binding(
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    raw_od_id = body.get("od_id")
    if not isinstance(raw_od_id, int) or isinstance(raw_od_id, bool):
        raise HTTPException(status_code=400, detail="od_id must be an integer")
    od_id = raw_od_id
    kds_id = str(body.get("kds_id") or "")
    if str(od_id) not in _ONTOLOGY_DOMAINS:
        raise HTTPException(status_code=404, detail="Ontology domain not found")
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    for binding in _ONTOLOGY_BINDINGS:
        if binding["kds_id"] != kds_id:
            continue
        if binding["od_id"] == od_id:
            return binding
        raise HTTPException(
            status_code=409,
            detail="Knowledge base is already bound to another ontology domain",
        )
    binding = {
        "id": max([int(item.get("id") or 0) for item in _ONTOLOGY_BINDINGS] or [0]) + 1,
        "od_id": od_id,
        "kds_id": kds_id,
        "kb_name": (_KNOWLEDGE_BASES.get(kds_id) or {}).get("kds_name"),
        "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _ONTOLOGY_BINDINGS.append(binding)
    _save_state()
    return binding


@app.delete(f"{_ONTOLOGY_PREFIX}/Bindings")
def delete_ontology_binding(
    od_id: int = Query(...),
    kds_id: str = Query(...),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    before = len(_ONTOLOGY_BINDINGS)
    _ONTOLOGY_BINDINGS[:] = [
        binding
        for binding in _ONTOLOGY_BINDINGS
        if not (binding["od_id"] == od_id and binding["kds_id"] == str(kds_id))
    ]
    if len(_ONTOLOGY_BINDINGS) == before:
        raise HTTPException(status_code=404, detail="Binding not found")
    _save_state()
    return JSONResponse(status_code=204, content=None)


# Confirmed real-contract routes: bind/unbind live on the tenant-scoped KB
# side and take no body; the domain-side list answers
# value/next_link/total_count without any BindingId. The legacy routes above
# stay for older demo seeds.
@app.post(f"{_KB_PREFIX}/{{kds_id}}/OntologyDomain/{{domain_id}}/Bind")
def bind_kb_to_ontology(
    kds_id: str,
    domain_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    if domain_id not in _ONTOLOGY_DOMAINS:
        raise HTTPException(status_code=404, detail="Ontology domain not found")
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    for binding in _ONTOLOGY_BINDINGS:
        if binding["kds_id"] != kds_id:
            continue
        if binding["od_id"] == int(domain_id):
            return {
                "domain_id": int(domain_id),
                "kb_id": kds_id,
                "id": binding.get("id"),
                "failed_kbs": [],
                "partial_failure": False,
            }
        raise HTTPException(
            status_code=409,
            detail="ONTOLOGY_KDS_BIND_CONFLICT(1055): knowledge base is already bound or unbinding",
        )
    binding = {
        "id": max([int(item.get("id") or 0) for item in _ONTOLOGY_BINDINGS] or [0]) + 1,
        "od_id": int(domain_id),
        "kds_id": kds_id,
        "kb_name": (_KNOWLEDGE_BASES.get(kds_id) or {}).get("kds_name"),
        "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _ONTOLOGY_BINDINGS.append(binding)
    _save_state()
    return {
        "domain_id": int(domain_id),
        "kb_id": kds_id,
        "id": binding["id"],
        "failed_kbs": [],
        "partial_failure": False,
    }


@app.post(f"{_KB_PREFIX}/{{kds_id}}/OntologyDomain/{{domain_id}}/Unbind")
def unbind_kb_from_ontology(
    kds_id: str,
    domain_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    before = len(_ONTOLOGY_BINDINGS)
    _ONTOLOGY_BINDINGS[:] = [
        binding
        for binding in _ONTOLOGY_BINDINGS
        if not (
            binding["od_id"] == int(domain_id) and binding["kds_id"] == kds_id
        )
    ]
    if len(_ONTOLOGY_BINDINGS) == before:
        raise HTTPException(status_code=404, detail="Binding not found")
    _save_state()
    return {
        "tag_clear_task": {
            "task_id": 456,
            "task_type": "ontology_tag_clear",
        }
    }


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Bindings")
def list_domain_bindings_real(
    domain_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    rows = [
        binding
        for binding in _ONTOLOGY_BINDINGS
        if binding["od_id"] == int(domain_id)
    ]
    total = len(rows)
    start = (page - 1) * page_size
    items = [
        {
            "binding_type": "ontology",
            "domain_id": row["od_id"],
            "kb_id": row["kds_id"],
        }
        for row in rows[start:start + page_size]
    ]
    next_link = (
        f"{_ONTOLOGY_PREFIX}/{domain_id}/Bindings?page={page + 1}&page_size={page_size}"
        if start + page_size < total
        else None
    )
    return {"value": items, "total_count": total, "next_link": next_link}


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}")
def get_ontology_domain(
    domain_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    domain = _ontology_domain_or_404(domain_id)
    # Confirmed contract wraps the row in a named `domain` object whose id key
    # is `id` (the list uses domain_id/od_id).
    return {
        "domain": {
            "id": int(domain_id),
            "name": domain.get("name"),
            "description": domain.get("description") or "",
            "create_time": domain.get("create_time"),
            "update_time": domain.get("update_time"),
            "entity_version": 1,
            "metadata_version": 1,
            "rule_version": 1,
        }
    }


@app.patch(f"{_ONTOLOGY_PREFIX}/{{domain_id}}")
def update_ontology_domain(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    domain = _ontology_domain_or_404(domain_id)
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        domain["name"] = name
    if "description" in body:
        domain["description"] = str(body.get("description") or "")
    _save_state()
    return domain


@app.delete(f"{_ONTOLOGY_PREFIX}/{{domain_id}}")
def delete_ontology_domain(
    domain_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    domain_id = str(domain_id)
    if domain_id not in _ONTOLOGY_DOMAINS:
        raise HTTPException(status_code=404, detail="Ontology domain not found")
    _ONTOLOGY_DOMAINS.pop(domain_id, None)
    _ONTOLOGY_ENTITIES.pop(domain_id, None)
    _ONTOLOGY_RELATIONS.pop(domain_id, None)
    _ONTOLOGY_METADATA.pop(domain_id, None)
    _ONTOLOGY_BINDINGS[:] = [
        binding for binding in _ONTOLOGY_BINDINGS if binding["od_id"] != int(domain_id)
    ]
    _save_state()
    return JSONResponse(status_code=204, content=None)


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Entities")
def list_ontology_entities(
    domain_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    size: Optional[int] = Query(None, ge=1, le=100),
    keyword: Optional[str] = None,
    kind: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    page_size = size or page_size
    _ontology_domain_or_404(domain_id)
    items = list(_ONTOLOGY_ENTITIES.get(str(domain_id), []))
    if kind:
        items = [item for item in items if item.get("kind") == kind]
    if keyword and keyword.strip():
        needle = keyword.strip().lower()
        items = [
            item
            for item in items
            if needle in str(item.get("api_name", "")).lower()
            or needle in str(item.get("display_name", "")).lower()
        ]
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start:start + page_size]
    next_link = (
        f"{_ONTOLOGY_PREFIX}/{domain_id}/Entities?page={page + 1}&page_size={page_size}"
        if start + page_size < total
        else None
    )
    return {
        "items": [_public_entity(item) for item in page_items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "next_link": next_link,
    }


@app.put(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Entities")
def create_ontology_entity(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    domain_id = str(domain_id)
    api_name = str(body.get("api_name") or "").strip()
    kind = str(body.get("kind") or "").lower()
    if not api_name or kind not in ("type", "entity"):
        raise HTTPException(status_code=400, detail="api_name and kind are required")
    entities = _ONTOLOGY_ENTITIES.setdefault(domain_id, [])
    for item in entities:
        if item.get("api_name") == api_name and item.get("kind") == kind:
            raise HTTPException(status_code=409, detail="Entity already exists")
    entity_id = _next_numeric_id([item.get("entity_id") for item in entities], 100)
    record = {
        "entity_id": entity_id,
        "api_name": api_name,
        "display_name": body.get("display_name") or api_name,
        "description": body.get("description") or "",
        "kind": kind,
        "type_id": body.get("type_id"),
        "properties": body.get("properties") or [],
        "primary_properties": body.get("primary_properties") or [],
        "parent_entities": body.get("parent_entities") or [],
        "synonym_entities": body.get("synonym_entities") or [],
        "child_entities": [],
        "chunk_count": 0,
        "extended_properties": [],
    }
    entities.append(record)
    _save_state()
    # Confirmed create answers a small receipt keyed by entity_id (or type_id).
    if kind == "type":
        return {
            "type_id": int(entity_id),
            "api_name": api_name,
            "display_name": record["display_name"],
            "description": record["description"],
        }
    return {
        "entity_id": int(entity_id),
        "api_name": api_name,
        "display_name": record["display_name"],
        "description": record["description"],
    }


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Entities/{{entity_id}}")
def get_ontology_entity(
    domain_id: str,
    entity_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    for item in _ONTOLOGY_ENTITIES.get(str(domain_id), []):
        if str(item.get("entity_id")) == str(entity_id):
            # Confirmed contract: named `entity` wrapper, no id inside, and a
            # permanently empty neighbor list.
            entity = _public_entity(item)
            entity.pop("entity_id", None)
            return {"entity": entity, "neighbor": []}
    raise HTTPException(status_code=404, detail="Entity not found")


@app.patch(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Entities/{{entity_id}}")
def update_ontology_entity(
    domain_id: str,
    entity_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    forbidden = {"parent_entities", "synonym_entities", "type_id", "kind", "api_name"}
    if forbidden.intersection(body):
        raise HTTPException(
            status_code=400,
            detail="parent_entities, synonym_entities, type_id, kind and api_name are not editable",
        )
    for item in _ONTOLOGY_ENTITIES.get(str(domain_id), []):
        if str(item.get("entity_id")) != str(entity_id):
            continue
        for key in ("display_name", "description", "properties", "primary_properties"):
            if key in body:
                item[key] = body.get(key)
        _save_state()
        return {
            "id": int(entity_id),
            "name": item.get("api_name"),
            "description": item.get("description") or "",
            "graph_updated": False,
        }
    raise HTTPException(status_code=404, detail="Entity not found")


@app.delete(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Entities/{{entity_id}}")
def delete_ontology_entity(
    domain_id: str,
    entity_id: str,
    kind: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    entities = _ONTOLOGY_ENTITIES.get(str(domain_id), [])
    remaining = [
        item
        for item in entities
        if str(item.get("entity_id")) != str(entity_id)
        or (kind and item.get("kind") != kind)
    ]
    if len(remaining) == len(entities):
        raise HTTPException(status_code=404, detail="Entity not found")
    _ONTOLOGY_ENTITIES[str(domain_id)] = remaining
    _save_state()
    return JSONResponse(status_code=204, content=None)


def _public_rule(item: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _rule_or_404(domain_id: str, rule_id: str) -> Dict[str, Any]:
    for item in _ONTOLOGY_RULES.get(str(domain_id), []):
        if str(item.get("rule_id")) == str(rule_id):
            return item
    raise HTTPException(status_code=404, detail="Rule not found")


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Rules")
def list_ontology_rules(
    domain_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    enabled_only: bool = False,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    items = list(_ONTOLOGY_RULES.get(str(domain_id), []))
    if enabled_only:
        items = [item for item in items if item.get("enabled")]
    items.sort(key=lambda item: int(item.get("rule_id") or 0))
    total = len(items)
    start = (page - 1) * size
    return {
        "value": [_public_rule(item) for item in items[start:start + size]],
        "total_count": total,
    }


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Rules/Count")
def count_ontology_rules(
    domain_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    return {"count": len(_ONTOLOGY_RULES.get(str(domain_id), []))}


@app.put(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Rules")
def create_ontology_rule(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    domain_id = str(domain_id)
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if len(name.encode("utf-8")) > 128:
        raise HTTPException(status_code=400, detail="name must not exceed 128 UTF-8 bytes")
    description = str(body.get("description") or "")
    if len(description.encode("utf-8")) > 512:
        raise HTTPException(
            status_code=400,
            detail="description must not exceed 512 UTF-8 bytes",
        )
    condition = body.get("condition")
    action = body.get("action")
    if not isinstance(condition, dict) or not isinstance(action, dict):
        raise HTTPException(status_code=400, detail="condition and action are required")
    rules = _ONTOLOGY_RULES.setdefault(domain_id, [])
    if len(rules) >= 100:
        raise HTTPException(status_code=400, detail="At most 100 rules are allowed")
    if any(item.get("name") == name for item in rules):
        raise HTTPException(status_code=409, detail="Rule name already exists")
    rule_id = max([int(item.get("rule_id") or 0) for item in rules] or [0]) + 1
    now = int(time.time())
    record = {
        "rule_id": rule_id,
        "name": name,
        "description": description,
        "enabled": bool(body.get("enabled", True)),
        "condition": condition,
        "action": action,
        # Confirmed rule contract uses created_time/updated_time in unix seconds.
        "created_time": now,
        "updated_time": now,
    }
    rules.append(record)
    _save_state()
    return _public_rule(record)


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Rules/{{rule_id}}")
def get_ontology_rule(
    domain_id: str,
    rule_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    return _public_rule(_rule_or_404(domain_id, rule_id))


@app.patch(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Rules/{{rule_id}}")
def update_ontology_rule(
    domain_id: str,
    rule_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    current = _rule_or_404(domain_id, rule_id)
    name = str(body.get("name") or current.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if any(
        item is not current and item.get("name") == name
        for item in _ONTOLOGY_RULES.get(str(domain_id), [])
    ):
        raise HTTPException(status_code=409, detail="Rule name already exists")
    for key in ("name", "description", "enabled", "condition", "action"):
        if key in body:
            current[key] = body.get(key)
    current["updated_time"] = int(time.time())
    _save_state()
    return _public_rule(current)


@app.delete(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Rules/{{rule_id}}")
def delete_ontology_rule(
    domain_id: str,
    rule_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    rules = _ONTOLOGY_RULES.get(str(domain_id), [])
    remaining = [item for item in rules if str(item.get("rule_id")) != str(rule_id)]
    if len(remaining) == len(rules):
        raise HTTPException(status_code=404, detail="Rule not found")
    _ONTOLOGY_RULES[str(domain_id)] = remaining
    _save_state()
    return JSONResponse(status_code=204, content=None)


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Metadata")
def list_ontology_metadata(
    domain_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    fields = list(_ONTOLOGY_METADATA.get(str(domain_id), []))
    total = len(fields)
    start = (page - 1) * page_size
    page_items = fields[start:start + page_size]
    next_link = (
        f"{_ONTOLOGY_PREFIX}/{domain_id}/Metadata?page={page + 1}&page_size={page_size}"
        if start + page_size < total
        else None
    )
    return {
        "value": page_items,
        "total_count": total,
        "next_link": next_link,
        "has_next": next_link is not None,
    }


@app.put(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Metadata")
def create_ontology_metadata(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    domain_id = str(domain_id)
    field_name = str(body.get("fieldName") or "").strip()
    field_type = str(body.get("fieldType") or "")
    if not field_name:
        raise HTTPException(status_code=400, detail="fieldName is required")
    if len(field_name) > 63 or len(field_name.encode("utf-8")) > 64:
        raise HTTPException(
            status_code=400,
            detail="fieldName must not exceed 63 characters or 64 UTF-8 bytes",
        )
    if field_type not in ("string", "number", "date"):
        raise HTTPException(status_code=422, detail="fieldType must be string, number or date")
    fields = _ONTOLOGY_METADATA.setdefault(domain_id, [])
    if len(fields) >= 20:
        raise HTTPException(status_code=400, detail="At most 20 metadata fields are allowed")
    if any(item["fieldName"] == field_name for item in fields):
        raise HTTPException(status_code=400, detail="fieldName already exists")
    all_ids = [
        int(item["id"])
        for group in _ONTOLOGY_METADATA.values()
        for item in group
        if str(item.get("id", "")).isdigit()
    ]
    record = {
        "id": (max(all_ids) + 1) if all_ids else 1,
        "fieldName": field_name,
        "fieldType": field_type,
        "columnIndex": len(fields) + 1,
    }
    fields.append(record)
    _save_state()
    # Confirmed create answers a sync receipt; task_id=-1 means no async task.
    return {
        "column_index": record["columnIndex"],
        "failed_kbs": [],
        "field_name": record["fieldName"],
        "field_type": record["fieldType"],
        "metadata_id": record["id"],
        "partial_failure": False,
        "task_id": -1,
    }


def _mock_metadata_field(domain_id: str, metadata_id: str) -> Optional[Dict[str, Any]]:
    for item in _ONTOLOGY_METADATA.get(str(domain_id), []):
        if str(item.get("id")) == str(metadata_id):
            return item
    return None


@app.post(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Metadata/BatchUnbindAsync")
def batch_unbind_ontology_metadata(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    ids = body.get("metadata_id_list") or []
    creator = str(body.get("creator") or "").strip()
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="metadata_id_list is required")
    if not creator:
        raise HTTPException(status_code=400, detail="creator is required")
    fields = _ONTOLOGY_METADATA.get(str(domain_id), [])
    known = {str(item.get("id")) for item in fields}
    if not {str(value) for value in ids}.issubset(known):
        raise HTTPException(status_code=404, detail="Metadata field not found")
    _save_state()
    return JSONResponse(
        status_code=200,
        content={
            "task_id": "mock-unbind-001",
            "status": "RUNNING",
            "progress": 0,
            "creator": creator,
        },
    )


@app.patch(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Metadata/{{metadata_id}}")
def rename_ontology_metadata_by_id(
    domain_id: str,
    metadata_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    domain_id = str(domain_id)
    new_name = str(body.get("fieldName") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="fieldName is required")
    if len(new_name) > 63 or len(new_name.encode("utf-8")) > 64:
        raise HTTPException(
            status_code=400,
            detail="fieldName must not exceed 63 characters or 64 UTF-8 bytes",
        )
    fields = _ONTOLOGY_METADATA.get(domain_id, [])
    current = _mock_metadata_field(domain_id, metadata_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Metadata field not found")
    if any(item["fieldName"] == new_name and item is not current for item in fields):
        raise HTTPException(status_code=400, detail="fieldName already exists")
    current["fieldName"] = new_name
    _save_state()
    return current


@app.delete(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Metadata/{{metadata_id}}")
def delete_ontology_metadata_by_id(
    domain_id: str,
    metadata_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    current = _mock_metadata_field(str(domain_id), metadata_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Metadata field not found")
    fields = _ONTOLOGY_METADATA.get(str(domain_id), [])
    _ONTOLOGY_METADATA[str(domain_id)] = [
        item for item in fields if item is not current
    ]
    _save_state()
    # Confirmed delete is synchronous and reports dropped KBs.
    return {
        "deleted": True,
        "dropped_kbs": [],
        "failed_kbs": [],
    }


@app.patch(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Metadata")
def rename_ontology_metadata(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    domain_id = str(domain_id)
    field_name = str(body.get("fieldName") or "").strip()
    new_name = str(body.get("newFieldName") or "").strip()
    if not field_name or not new_name:
        raise HTTPException(status_code=400, detail="fieldName and newFieldName are required")
    if len(new_name) > 63 or len(new_name.encode("utf-8")) > 64:
        raise HTTPException(
            status_code=400,
            detail="newFieldName must not exceed 63 characters or 64 UTF-8 bytes",
        )
    fields = _ONTOLOGY_METADATA.get(domain_id, [])
    if any(item["fieldName"] == new_name for item in fields):
        raise HTTPException(status_code=400, detail="fieldName already exists")
    for item in fields:
        if item["fieldName"] == field_name:
            item["fieldName"] = new_name
            _save_state()
            return item
    raise HTTPException(status_code=404, detail="Metadata field not found")


@app.delete(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Metadata")
def delete_ontology_metadata(
    domain_id: str,
    fieldName: str = Query(...),
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    domain_id = str(domain_id)
    bound_kds = {
        binding["kds_id"]
        for binding in _ONTOLOGY_BINDINGS
        if binding["od_id"] == int(domain_id)
    }
    for kds_id in bound_kds:
        for chunk in _ONTOLOGY_CHUNKS_BY_KB.get(kds_id, []):
            if fieldName in (chunk.get("metadata") or {}):
                raise HTTPException(
                    status_code=400,
                    detail="Metadata field is in use by chunks and cannot be deleted",
                )
    fields = _ONTOLOGY_METADATA.get(domain_id, [])
    remaining = [item for item in fields if item["fieldName"] != fieldName]
    if len(remaining) == len(fields):
        raise HTTPException(status_code=404, detail="Metadata field not found")
    _ONTOLOGY_METADATA[domain_id] = remaining
    _save_state()
    return JSONResponse(status_code=204, content=None)


# =============================================================================
# Relations, tasks and KB-side chunk aliases (confirmed real contracts)
# =============================================================================

_KB_SIDE_PREFIX = "/KnowledgeBase/KnowledgeBases"
_TASK_STORE: List[Dict[str, Any]] = [
    {
        "id": "1",
        "task_type": "metadata_index_create",
        "status": "completed",
        "progress": 100,
        "description": "",
        "error_message": "",
        "start_time": 1794901958,
        "end_time": 1794901958,
    },
    {
        "id": "2",
        "task_type": "ontology_tag_clear",
        "status": "failed",
        "progress": 50,
        "description": "",
        "error_message": "mock tag clear failure",
        "start_time": 1794902000,
        "end_time": 1794902300,
    },
]


def _entity_by_api_name(domain_id: str, api_name: str) -> Optional[Dict[str, Any]]:
    for item in _ONTOLOGY_ENTITIES.get(str(domain_id), []):
        if item.get("api_name") == api_name:
            return item
    return None


def _relation_endpoint(domain_id: str, kind: str, entity_id: Any) -> Dict[str, Any]:
    for item in _ONTOLOGY_ENTITIES.get(str(domain_id), []):
        if str(item.get("entity_id")) == str(entity_id):
            return {
                "entity_id": item.get("entity_id"),
                "api_name": item.get("api_name"),
                "display_name": item.get("display_name"),
                "kind": item.get("kind"),
            }
    raise HTTPException(status_code=404, detail="Relation endpoint not found")


def _relation_rows(domain_id: str, relation_type: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in _ONTOLOGY_RELATIONS.get(str(domain_id), []):
        api_name = str(item.get("api_name") or "")
        if relation_type and api_name != relation_type:
            continue
        if "subject_entity" in item:
            rows.append(item)
            continue
        source = _entity_by_api_name(domain_id, str(item.get("source_api_name")))
        target = _entity_by_api_name(domain_id, str(item.get("object_api_name")))
        rows.append(
            {
                "relation_id": item.get("relation_id"),
                "api_name": api_name,
                "display_name": item.get("display_name") or "",
                "subject_entity": {
                    "entity_id": (source or {}).get("entity_id"),
                    "api_name": (source or {}).get("api_name"),
                    "display_name": (source or {}).get("display_name"),
                    "kind": (source or {}).get("kind"),
                },
                "object_entity": {
                    "entity_id": (target or {}).get("entity_id"),
                    "api_name": (target or {}).get("api_name"),
                    "display_name": (target or {}).get("display_name"),
                    "kind": (target or {}).get("kind"),
                },
                "create_time": item.get("create_time"),
            }
        )
    return rows


@app.get(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Relations")
def list_ontology_relations(
    domain_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    relation_type: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    rows = _relation_rows(domain_id, relation_type)
    total = len(rows)
    start = (page - 1) * size
    return {
        "items": rows[start:start + size],
        "page": page,
        "page_size": size,
        "total": total,
        "next_link": None,
    }


@app.put(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Relations")
def create_ontology_relation(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    api_name = str(body.get("api_name") or "")
    if api_name not in ("is", "is-a"):
        raise HTTPException(status_code=400, detail="api_name must be is or is-a")
    subject = _relation_endpoint(domain_id, body.get("source_kind"), body.get("source_id"))
    obj = _relation_endpoint(domain_id, body.get("object_kind"), body.get("object_id"))
    rows = _ONTOLOGY_RELATIONS.setdefault(str(domain_id), [])
    relation_id = max([int(item.get("relation_id") or 0) for item in rows] or [0]) + 1
    rows.append(
        {
            "relation_id": relation_id,
            "api_name": api_name,
            "display_name": body.get("display_name") or "",
            "subject_entity": subject,
            "object_entity": obj,
            "create_time": int(time.time()),
        }
    )
    _save_state()
    return {"message": "create relation success", "relation_id": relation_id}


@app.delete(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/Relations/{{relation_id}}")
def delete_ontology_relation(
    domain_id: str,
    relation_id: str,
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)
    _ontology_domain_or_404(domain_id)
    rows = _ONTOLOGY_RELATIONS.get(str(domain_id), [])
    remaining = [
        item for item in rows if str(item.get("relation_id")) != str(relation_id)
    ]
    if len(remaining) == len(rows):
        raise HTTPException(status_code=404, detail="Relation not found")
    _ONTOLOGY_RELATIONS[str(domain_id)] = remaining
    _save_state()
    return JSONResponse(status_code=204, content=None)


@app.get(f"/KnowledgeBase/Tenants/{TENANT}/Tasks")
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task_type: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    rows = [
        item for item in _TASK_STORE if not task_type or item["task_type"] == task_type
    ]
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "page": page,
        "page_size": page_size,
        "task_count": total,
        "total": total,
        "task_list": rows[start:start + page_size],
    }


@app.get(f"/KnowledgeBase/Tenants/{TENANT}/Tasks/{{task_id}}")
def get_task(
    task_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    for item in _TASK_STORE:
        if str(item["id"]) == str(task_id):
            return item
    raise HTTPException(status_code=404, detail="Task not found")


@app.get(f"{_KB_SIDE_PREFIX}/{{kds_id}}/Chunks")
def list_chunks_kb_side(
    kds_id: str,
    file_uuid: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    return list_chunks(
        kds_id=kds_id,
        file_uuid=file_uuid or "",
        page=page,
        page_size=page_size,
        authorization=authorization,
    )


@app.get(f"{_KB_SIDE_PREFIX}/{{kds_id}}/Chunks/{{chunk_id}}")
def get_chunk_kb_side(
    kds_id: str,
    chunk_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    return get_chunk(
        kds_id=kds_id, chunk_id=chunk_id, authorization=authorization
    )


@app.patch(f"{_KB_SIDE_PREFIX}/{{kds_id}}/Chunks/BatchMetadataJson")
def batch_chunk_metadata_kb_side(
    kds_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    return batch_chunk_metadata(
        kds_id=kds_id, body=body, authorization=authorization
    )


def _export_entity(item: Dict[str, Any], include_properties: bool) -> Dict[str, Any]:
    result = {
        "api_name": item.get("api_name"),
        "display_name": item.get("display_name"),
        "description": item.get("description") or "",
    }
    if include_properties:
        result["properties"] = item.get("properties") or []
        result["primary_properties"] = item.get("primary_properties") or []
        result["source_info"] = item.get("source_info") or []
    return result


@app.post(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/batch/export")
def export_ontology(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    domain = _ontology_domain_or_404(domain_id)
    raw_domain_id = body.get("DOMAIN_ID")
    if not isinstance(raw_domain_id, int) or isinstance(raw_domain_id, bool):
        raise HTTPException(status_code=400, detail="DOMAIN_ID must be an integer")
    if raw_domain_id != int(domain_id):
        raise HTTPException(status_code=400, detail="DOMAIN_ID does not match the path domain")
    include_properties = body.get("INCLUDE_PROPERTIES", True) is not False
    include_relations = body.get("INCLUDE_RELATIONS", True) is not False
    requested_kind = body.get("KIND")
    entities = list(_ONTOLOGY_ENTITIES.get(str(domain_id), []))
    types = [
        _export_entity(item, include_properties)
        for item in entities
        if item.get("kind") == "type" and requested_kind in (None, "", "type")
    ]
    entity_rows = [
        _export_entity(item, include_properties)
        for item in entities
        if item.get("kind") == "entity" and requested_kind in (None, "", "entity")
    ]
    relations = []
    if include_relations:
        relations = [
            {
                "api_name": item.get("api_name"),
                "display_name": item.get("display_name"),
                "source_api_name": item.get("source_api_name"),
                "source_kind": item.get("source_kind"),
                "object_api_name": item.get("object_api_name"),
                "object_kind": item.get("object_kind"),
                "source_ids": item.get("source_ids") or [],
            }
            for item in _ONTOLOGY_RELATIONS.get(str(domain_id), [])
        ]
    total = len(types) + len(entity_rows) + len(relations)
    if total > _ONTOLOGY_ASYNC_THRESHOLD:
        return {
            "code": 200,
            "message": "OK",
            "data": {
                "task_id": f"ontology-export-{uuid.uuid4().hex[:12]}",
                "status": "pending",
                "progress": 0,
            },
        }
    return {
        "code": 200,
        "message": "OK",
        "data": {
            domain["name"]: {
                "display_name": domain["name"],
                "description": domain.get("description") or "",
                "types": types,
                "entities": entity_rows,
                "relations": relations,
            }
        },
    }


@app.post(f"{_ONTOLOGY_PREFIX}/{{domain_id}}/batch/import")
def import_ontology(
    domain_id: str,
    body: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_auth(authorization)
    domain_id = str(domain_id)
    _ontology_domain_or_404(domain_id)
    # Confirmed payload: {"<target domain name>": {types, entities, relations}}.
    # The legacy flat DOMAIN_ID/ENTITIES/RELATIONS shape stays accepted.
    incoming_types: List[Any] = []
    incoming_entities: List[Any] = []
    incoming_relations: List[Any] = []
    if "DOMAIN_ID" in body:
        raw_domain_id = body.get("DOMAIN_ID")
        if not isinstance(raw_domain_id, int) or isinstance(raw_domain_id, bool):
            raise HTTPException(status_code=400, detail="DOMAIN_ID must be an integer")
        if raw_domain_id != int(domain_id):
            raise HTTPException(status_code=400, detail="DOMAIN_ID does not match the path domain")
        incoming_entities = body.get("ENTITIES") or []
        incoming_relations = body.get("RELATIONS") or []
    else:
        group = next(
            (
                value
                for value in body.values()
                if isinstance(value, dict) and ({"types", "entities", "relations"} & set(value))
            ),
            None,
        )
        if group is None:
            raise HTTPException(status_code=400, detail="import payload is invalid")
        incoming_types = group.get("types") or []
        incoming_entities = group.get("entities") or []
        incoming_relations = group.get("relations") or []
    incoming = [
        ("type", item) for item in incoming_types
    ] + [("entity", item) for item in incoming_entities]
    total = len(incoming) + len(incoming_relations)
    if total > _ONTOLOGY_ASYNC_THRESHOLD:
        return {
            "execution_mode": "async",
            "task_id": 12345,
            "task_type": "ontology_batch_import",
            "status": "pending",
            "progress": 0,
            "result": None,
        }

    entities = _ONTOLOGY_ENTITIES.setdefault(domain_id, [])
    existing = {(item.get("api_name"), item.get("kind")) for item in entities}
    imported_count = 0
    skipped_count = 0
    failed_count = 0
    errors: List[Dict[str, Any]] = []

    for index, (kind, item) in enumerate(incoming):
        if not isinstance(item, dict):
            failed_count += 1
            errors.append(
                {
                    "index": index,
                    "type": kind,
                    "api_name": None,
                    "error_code": 4001,
                    "message_zh": "条目不是对象",
                    "message_en": "Item is not an object",
                }
            )
            continue
        api_name = str(item.get("api_name") or "").strip()
        if not api_name:
            failed_count += 1
            errors.append(
                {
                    "index": index,
                    "type": kind,
                    "api_name": None,
                    "error_code": 4001,
                    "message_zh": "api_name 不合法",
                    "message_en": "api_name is invalid",
                }
            )
            continue
        if (api_name, kind) in existing:
            skipped_count += 1
            continue
        if api_name in _ONTOLOGY_IMPORT_FAIL_API_NAMES:
            failed_count += 1
            errors.append(
                {
                    "index": index,
                    "type": "entity",
                    "api_name": api_name,
                    "error_code": 4002,
                    "message_zh": "模拟导入失败",
                    "message_en": "Simulated import failure",
                }
            )
            continue
        record = {
            "entity_id": _next_numeric_id(
                [item.get("entity_id") for item in entities], 100
            ),
            "api_name": api_name,
            "display_name": item.get("display_name") or api_name,
            "description": item.get("description") or "",
            "kind": kind,
            "type_id": item.get("type_id"),
            "properties": item.get("properties") or [],
            "primary_properties": item.get("primary_properties") or [],
            "parent_entities": [],
            "synonym_entities": [],
        }
        entities.append(record)
        existing.add((api_name, kind))
        imported_count += 1

    entity_lookup = {
        item.get("api_name"): item.get("kind") for item in entities
    }
    relation_imported = 0
    relation_failed = 0
    relation_rows = _ONTOLOGY_RELATIONS.setdefault(domain_id, [])
    existing_relations = {item.get("api_name") for item in relation_rows}
    for index, item in enumerate(incoming_relations):
        if not isinstance(item, dict):
            relation_failed += 1
            errors.append(
                {
                    "index": index,
                    "type": "relation",
                    "api_name": None,
                    "error_code": 4001,
                    "message_zh": "关系条目不是对象",
                    "message_en": "Relation item is not an object",
                }
            )
            continue
        api_name = str(item.get("api_name") or "").strip()
        source = str(item.get("source_api_name") or "").strip()
        target = str(item.get("object_api_name") or "").strip()
        if (
            not api_name
            or source not in entity_lookup
            or target not in entity_lookup
        ):
            relation_failed += 1
            errors.append(
                {
                    "index": index,
                    "type": "relation",
                    "api_name": api_name or None,
                    "error_code": 4001,
                    "message_zh": "关系端点无法定位",
                    "message_en": "Relation endpoint cannot be resolved",
                }
            )
            continue
        if api_name in existing_relations and source in {
            item.get("source_api_name") for item in relation_rows
        }:
            relation_imported += 1
            continue
        relation_rows.append(
            {
                "api_name": api_name,
                "display_name": item.get("display_name") or api_name,
                "source_api_name": source,
                "source_kind": item.get("source_kind") or entity_lookup[source],
                "object_api_name": target,
                "object_kind": item.get("object_kind") or entity_lookup[target],
                "source_ids": item.get("source_ids") or [],
            }
        )
        relation_imported += 1

    _save_state()
    return {
        "execution_mode": "sync",
        "task_id": None,
        "status": "completed",
        "progress": 100,
        "result": {
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "relation_imported": relation_imported,
            "relation_failed": relation_failed,
            "first_error": errors[0] if errors else None,
            "errors": errors,
        },
    }


@app.post("/_mock/ontology-file")
def seed_ontology_file(
    kds_id: str = Query(...),
    file_name: str = Query("ontology-chunk.txt"),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Attach one completed file with three chunks to a product-created KB.

    The ontology UI lists files through the normal KnowledgeFiles endpoint and
    then reads chunks through the ontology chunk proxy. A newly created KB has
    no ingested files, so this test-only hook supplies a deterministic file and
    chunks without bypassing either product endpoint.
    """
    _check_auth(authorization)
    if kds_id not in _KNOWLEDGE_BASES:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    file_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mock-ontology:{kds_id}:{file_name}"))
    documents = _DOCUMENTS_BY_KB.setdefault(kds_id, [])
    if not any(_same_file_uuid(document.get("file_uuid"), file_uuid) for document in documents):
        documents.append(
            {
                "file_uuid": file_uuid,
                "file_ino_no": 7000 + len(documents),
                "file_name": file_name,
                "file_size": 2048,
                "file_type": "txt",
                "create_time": int(time.time()),
                "status": 1,
            }
        )
    existing_ids = {
        str(chunk.get("chunk_id")) for chunk in _ONTOLOGY_CHUNKS_BY_KB.get(kds_id, [])
    }
    chunk_ids: List[int] = []
    for index in range(3):
        chunk_id = 5000 + len(_ONTOLOGY_CHUNKS_BY_KB.get(kds_id, [])) + index + 1
        if str(chunk_id) in existing_ids:
            continue
        _ONTOLOGY_CHUNKS_BY_KB.setdefault(kds_id, []).append(
            {
                "chunk_id": chunk_id,
                "chunk_text": f"本体标注演示切片 {index + 1}：该片段用于验证 Metadata 写入与回显。",
                "chunk_type": "TEXT",
                "file_name": file_name,
                "file_url": f"aidp://{file_uuid}",
                "page_ids": [index + 1],
                "metadata": {},
                "_file_uuid": file_uuid,
            }
        )
        chunk_ids.append(chunk_id)
    _save_state()
    return {"file_uuid": file_uuid, "file_name": file_name, "chunk_ids": chunk_ids}


@app.post("/_mock/ontology-import-fail")
def configure_ontology_import_fail(
    api_names: str = Query(default=""),
) -> Dict[str, Any]:
    _ONTOLOGY_IMPORT_FAIL_API_NAMES.clear()
    _ONTOLOGY_IMPORT_FAIL_API_NAMES.update(
        name.strip() for name in api_names.split(",") if name.strip()
    )
    return {"api_names": sorted(_ONTOLOGY_IMPORT_FAIL_API_NAMES)}


@app.post("/_mock/ontology-metadata-fail")
def configure_ontology_metadata_fail(
    chunk_ids: str = Query(default=""),
) -> Dict[str, Any]:
    _ONTOLOGY_METADATA_FAIL_CHUNK_IDS.clear()
    _ONTOLOGY_METADATA_FAIL_CHUNK_IDS.update(
        chunk_id.strip() for chunk_id in chunk_ids.split(",") if chunk_id.strip()
    )
    return {"chunk_ids": sorted(_ONTOLOGY_METADATA_FAIL_CHUNK_IDS)}


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
    _DOCUMENT_CHUNKS_BY_KB.clear()
    _DOCUMENT_CHUNK_GENERATED_FILES.clear()

    _ONTOLOGY_IMPORT_FAIL_API_NAMES.clear()
    _ONTOLOGY_METADATA_FAIL_CHUNK_IDS.clear()
    _SENSITIVE_WORDS.clear()
    _seed_initial_data()
    _seed_ontology_data()
    _ensure_ontology_chunks()
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
    parser.add_argument("--preview-dir", type=Path, help="Optional UUID-named converted PDF fixtures for local preview demos")
    parser.add_argument("--document-dir", type=Path, help="Optional UUID-named original byte fixtures for local demos")
    args = parser.parse_args()
    _PREVIEW_FIXTURE_DIR = args.preview_dir.resolve() if args.preview_dir else None
    _DOCUMENT_FIXTURE_DIR = args.document_dir.resolve() if args.document_dir else None
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
