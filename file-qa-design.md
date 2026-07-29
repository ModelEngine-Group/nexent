# Nexent 文件问答功能设计方案

## 1. 概述

### 1.1 背景

参考阿里云百炼智能体应用的文件问答能力，为 Nexent 添加会话级文件问答功能。用户在聊天中上传文档文件后，系统自动解析文件内容，支持基于文件内容的多轮问答。

### 1.2 目标

- 支持文档类文件的全文引用和切片检索两种问答模式
- 文件生命周期跟随 conversation，用户回到历史对话可继续基于已上传文件问答
- 多轮对话中上传的文件自动累积，后续轮次可引用所有已上传文件
- 最大化复用现有基础设施（ES、data_process、KnowledgeBaseSearchTool）

### 1.3 范围

**本期实现：**
- 文档类文件（pdf/docx/doc/pptx/ppt/xlsx/xls/md/txt/csv/json/xml/html/epub）的全文引用和切片检索
- 统一处理流水线（全文提取 + 分片入库同时执行），查询时按 Agent 配置的 `file_mode` 决定使用方式
- 异步分片入库

**已有能力（无需改动）：**
- 图片/音频/视频的多模态处理——已通过 AnalyzeImageTool / AnalyzeAudioTool / AnalyzeVideoTool 实现，等价于百炼的"自定义处理"模式，本期零改动即可继续使用

**不在本期范围：**
- 文件持久化到永久知识库

---

## 2. 现有能力分析

### 2.1 已有基础设施

| 组件 | 位置 | 能力 | 复用方式 |
|------|------|------|---------|
| **文件上传** | `frontend/lib/chat/chatAttachmentUtils.ts` | 聊天中上传文件到 MinIO，构建 `minio_files` | 直接复用，零改动 |
| **文件 URL 拼接** | `backend/agents/create_agent_info.py` → `join_minio_file_description_to_query` | 将文件 URL 拼入 prompt，LLM 通过工具处理 | 改造：增加全文引用/切片检索分支 |
| **文件解析** | `sdk/nexent/data_process/core.py` → `DataProcessCore` | 解析文档为 chunks（Unstructured + OpenPyxl + JSON） | 直接复用 `file_process()` |
| **向量化入库** | `sdk/nexent/vector_database/elasticsearch_core.py` → `ElasticSearchCore` | 文档向量化写入 ES 索引 | 直接复用 `vectorize_documents()` |
| **混合检索** | `sdk/nexent/core/tools/knowledge_base_search_tool.py` → `KnowledgeBaseSearchTool` | BM25 + 向量混合检索，支持多索引 | 复用：在 `index_names` 中追加临时索引 |
| **异步任务管理** | `backend/agents/preprocess_manager.py` → `PreprocessManager` | 会话级异步任务注册/取消/状态查询 | 直接复用 |
| **多媒体处理** | `sdk/nexent/core/tools/analyze_image_tool.py` 等 | 图片/音频/视频通过 VL 模型处理 | 无需改动，已覆盖自定义处理模式 |

### 2.2 文件解析器支持矩阵

| 解析器 | 支持格式 | 底层依赖 |
|--------|---------|---------|
| UnstructuredProcessor | `.txt` `.pdf` `.docx` `.doc` `.html` `.htm` `.md` `.rtf` `.odt` `.pptx` `.ppt` `.json` `.epub` `.csv` `.xml` | unstructured 库 |
| OpenPyxlProcessor | `.xlsx` `.xls` | openpyxl |
| JSONChunkProcessor | `.json`（在 UnstructuredProcessor 内部调用） | orjson |

### 2.3 现有聊天文件上传流程

```
前端: chatAttachmentUtils.uploadAttachments()
  → storageService.uploadFiles() → MinIO
  → buildMinioFilePayload() → { messageAttachments, minioFiles }

后端: agent_app.py → agent_service.py → create_agent_run_info()
  → join_minio_file_description_to_query(minio_files, query, history)
  → 将文件 URL 拼入 prompt 文本
  → LLM 自主调用 analyze_image / analyze_text_file 等工具
```

**当前局限**：文件只是以 URL 形式拼入 prompt，依赖 LLM 调用工具读取。不支持将文件内容直接注入上下文（全文引用），也不支持将文件分片后做向量检索（切片检索）。

---

## 3. 三种处理模式

### 3.1 模式概览

| 模式 | 处理方式 | 适用场景 | 向量库依赖 |
|------|---------|---------|-----------|
| **全文引用** | 解析文件全文 → 拼入 LLM context | 短文档摘要、翻译、润色 | 无 |
| **切片检索 (RAG)** | 分片 → embedding → 写入 ES → 检索 top-k | 长文档问答、多文件交叉检索 | ES 临时索引 |
| **自定义处理** | 文件 URL 传给 LLM，LLM 调用工具处理 | 图片/音频/视频分析 | 无 |

### 3.2 处理模式与 Agent 配置

处理模式由 Agent 的 `file_preprocess` 配置决定：

```python
# Agent 配置 (ag_tenant_agent_t.file_preprocess JSONB)
{
    "enable": true,
    "config": {
        "file_mode": "full_text_reference" | "chunk_search",
        "rerank_top_n": 5,
        "max_parse_length": 2000,
        "prompt_max_token_length": 5000,
        "prompt_strategy_name": "auto"
    }
}
```

`file_mode` 决定**查询时**如何使用文件内容，但**处理时统一执行两种预处理**：

```
文件上传
  │
  ├─ 多媒体文件（图片/音频/视频）
  │   └─ 自定义处理（现有逻辑，不变）
  │
  └─ 文档文件（pdf/docx/md/txt/...）
      │
      └─ 统一处理流水线（两种都做）：
          ├─ 1. 提取全文 → 存 MinIO (fulltext_key)
          └─ 2. 分片 → embedding → 写入 ES (chunks)
```

**为什么两种都做**：`file_mode` 是 Agent 级别的配置，管理员随时可能修改。如果只做一种，用户回到历史对话时可能发现文件不可用（如从全文引用切到切片检索，但文件没有 chunks）。两种都处理的额外成本很低（小文件的 chunk 数少，大文件的全文提取已是 RAG 流程的前置步骤），彻底消除模式切换问题。

**查询时根据当前 Agent 的 `file_mode` 决定读哪个**：

```
file_mode = "full_text_reference"
  → 读 fulltext_key 中的全文 → 拼入 LLM context
  → 受 max_parse_length 和 prompt_max_token_length 限制

file_mode = "chunk_search"
  → KnowledgeBaseSearchTool 检索 ES chunks
  → 受 rerank_top_n 限制
```

**全文引用的上下文保护**：

使用 Agent 配置的 `max_parse_length` 和 `prompt_max_token_length` 控制：

```
单文件截断: 文件文本 token 数 > max_parse_length → 截断末尾
总量截断:   所有文件拼接后 token 数 > prompt_max_token_length → 从最后拼接文件的末尾开始截断
```

### 3.3 Document Grounding（来源溯源）

多文件问答中，模型可能混淆文件来源或跨文件幻觉拼接。需要在两个层面强制 grounding：

#### 3.3.1 全文引用模式 — 结构化文件边界

用 XML 标签包裹每个文件，替代简单的文本拼接：

```xml
<uploaded_files>

<file name="Q3财报.pdf" id="file_1">
[文件完整内容]
</file>

<file name="竞品分析.docx" id="file_2">
[文件完整内容]
</file>

</uploaded_files>
```

配合 system prompt 中的 grounding 指令：

```
You have access to the user's uploaded files enclosed in <uploaded_files> tags.
Rules:
1. When answering, ALWAYS cite the source file using【file_name】format.
2. If information comes from multiple files, cite each source separately.
3. NEVER combine or merge facts from different files into a single unsourced statement.
4. If a question can only be answered by one file, explicitly state which file you are referencing.
5. If files contain conflicting information, present both versions with their respective sources.
```

#### 3.3.2 切片检索 (RAG) 模式 — chunk 级来源标注

**入库时**：每个 chunk 必须携带文件来源元数据：

```python
for chunk in chunks:
    chunk["path_or_url"] = object_name      # MinIO 路径
    chunk["filename"] = original_filename    # 原始文件名（用户可见）
    chunk["source_type"] = "minio"
    chunk["title"] = original_filename       # 确保 title 非空
```

**返回 LLM 时**：改造 `to_model_dict()`，在文件问答场景下补充 `source` 字段：

```python
# 现有返回：{"title": "xxx", "text": "...", "index": "kb0"}
# 改造后：  {"title": "xxx", "text": "...", "index": "kb0", "source": "Q3财报.pdf"}
```

这样 LLM 每条检索结果都能看到具体来源文件名，配合 system prompt 指令实现引用标注。

**KnowledgeBaseSearchTool 的 system prompt 追加**：

```
When citing search results, always include the source filename in【】brackets.
If results from different files conflict, present both with sources and let the user decide.
Do not synthesize information across different source files without explicitly noting each source.
```

#### 3.3.3 前端引用展示

现有的 `cite_index` + `tool_sign` 机制已支持引用下标展示（如 `[1]` `[2]`）。前端点击引用下标可展开看到 `filename` + `text` 片段。文件问答场景无需额外前端改动，复用现有引用 UI。

文件类型判断依据：

```python
DOCUMENT_EXTENSIONS = {
    ".txt", ".pdf", ".docx", ".doc", ".html", ".htm", ".md", ".rtf",
    ".odt", ".pptx", ".ppt", ".json", ".epub", ".csv", ".xml",
    ".xlsx", ".xls"
}

MULTIMEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp",          # 图片
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv",   # 视频
    ".aac", ".amr", ".flac", ".m4a", ".mp3", ".ogg", ".wav",   # 音频
}
```

---

## 4. 向量库选型与设计

### 4.1 选型：复用现有 Elasticsearch

**不引入新组件**，直接复用已部署的 Elasticsearch 实例和 `ElasticSearchCore` 接口。

选型理由：

| 维度 | Elasticsearch (现有) | 引入 Milvus/Qdrant |
|------|---------------------|-------------------|
| 部署成本 | 零，已在线 | 新增容器 + 运维 |
| 代码复用 | `VectorDatabaseCore` 接口完整 | 需新写 adapter |
| 能力匹配 | dense vector + BM25 混合检索 | 纯向量检索更强，但文件问答不需要 |
| 临时索引 | 原生支持 index CRUD + TTL | 需额外管理 collection 生命周期 |
| 团队熟悉度 | 已有完整实践 | 有学习曲线 |

### 4.2 共享索引设计

**核心原则**：使用租户级共享索引，避免 index-per-conversation 导致的 ES 索引数爆炸。

#### 4.2.1 为什么不用 index-per-conversation

index-per-conversation（如 `conversation_file_{tenant_id}_{conversation_id}`）在高并发场景下有严重的扩展性问题：

| 风险 | 影响 |
|------|------|
| index 数量随会话线性增长 | 3 节点 ES 集群建议 shard < 3000，每个 index 至少 2 shard → 上限 ~1500 并发会话 |
| cluster state 膨胀 | ES cluster state 全量存内存，index 元数据增长导致 master 节点压力增大 |
| 24h TTL 清理滞后 | 高峰期积压大量索引，`beforeunload` 不可靠（浏览器不保证触发） |
| shard 碎片化 | 大量小 index 的小 shard 浪费资源、降低检索效率 |

#### 4.2.2 租户级共享索引方案

每个租户共享 **1 个** ES 索引，通过 `conversation_id` 字段做查询隔离：

```
索引名:  conversation_file_{tenant_id}  （每个租户 1 个，不随会话增长）
文档字段:
  conversation_id  → "conv_abc123"   （查询时 filter）
  content          → "..."           （chunk 文本）
  embedding        → [0.1, 0.2, ...]  （向量）
  filename         → "report.pdf"    （原始文件名）
  path_or_url      → "xxx/yyy"       （MinIO 路径）
  source_type      → "minio"
  created_at       → "2026-07-03T10:00:00Z"
```

**索引数量对比**：

```
index-per-conversation:  O(并发会话数)   → 可能数千
租户级共享索引:           O(租户数)       → 通常几十到几百
```

#### 4.2.3 检索隔离

检索时通过 `bool filter` 限定 `conversation_id`，确保只检索当前会话的文件 chunks：

```python
# 构建检索请求时，注入 conversation_id filter
search_filter = {
    "bool": {
        "filter": [
            {"term": {"conversation_id": conversation_id}}
        ]
    }
}
```

对 `KnowledgeBaseSearchTool` 的适配：在文件问答场景下，传入 `_internal_document_paths` 或扩展 filter 条件，将检索范围限定到当前 conversation 的 chunks。

#### 4.2.4 元数据存储

使用 PostgreSQL 持久化存储，文件元数据跟随 conversation 生命周期：

```sql
CREATE TABLE conversation_file_t (
    id              BIGSERIAL       PRIMARY KEY,
    conversation_id VARCHAR(64)     NOT NULL,
    tenant_id       VARCHAR(64)     NOT NULL,
    object_name     VARCHAR(512)    NOT NULL,
    filename        VARCHAR(256)    NOT NULL,
    content_hash    VARCHAR(64),
    status          VARCHAR(16)     NOT NULL DEFAULT 'pending',
    chunk_count     INT             NOT NULL DEFAULT 0,
    fulltext_key    VARCHAR(512),
    embedding_model VARCHAR(128),
    error_message   TEXT,
    create_time     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by      VARCHAR(100),
    updated_by      VARCHAR(100),
    delete_flag     VARCHAR(1)      DEFAULT 'N'
);

CREATE INDEX idx_conv_file_conv_id ON conversation_file_t(conversation_id);
CREATE INDEX idx_conv_file_tenant ON conversation_file_t(tenant_id);
CREATE UNIQUE INDEX udx_conv_file_obj ON conversation_file_t(conversation_id, object_name);
```

**设计要点**：

- 每个上传文件对应一条记录，不再用 Redis Hash 存 JSON 数组
- `fulltext_key`：全文引用模式下，解析后的纯文本存回 MinIO（避免 PG 存大文本），此字段记录 MinIO 路径
- 文件状态、chunk 数量等直接查表，不依赖 Redis TTL

#### 4.2.5 生命周期管理

```
索引创建时机:
  租户首次使用文件问答（RAG 模式）时，创建 conversation_file_{tenant_id} 索引
  后续会话复用同一索引，无需重复创建

数据清理 (两种触发):
  1. 用户删除 conversation
     → delete_by_query(conversation_id=xxx) + 删除 PG 中对应记录 + 删除 MinIO 中的全文缓存
  2. 定时任务（兜底）
     → 扫描 ES 中的 conversation_id，检查 PG 中是否仍存在该 conversation
     → 不存在 → 孤儿数据，执行 delete_by_query 清理

索引本身不删除（租户级长期存在），只清理已删除 conversation 的 documents
页面关闭/刷新不触发任何清理 — 文件跟随 conversation 持久存在
```

#### 4.2.6 定时清理任务（孤儿数据清理）

```python
# 复用现有 auto_summary_scheduler.py 的调度模式
# 每天凌晨执行一次，清理已删除 conversation 残留的 ES chunks

async def cleanup_orphan_conversation_file_chunks():
    """Clean up ES chunks whose conversation no longer exists in the database."""
    vdb_core = get_vdb_core()
    db = get_db_session()

    all_indices = vdb_core.get_user_indices("conversation_file_*")

    for index_name in all_indices:
        unique_conversations = vdb_core.get_unique_field_values(
            index_name, "conversation_id"
        )

        for conversation_id in unique_conversations:
            conversation_exists = db.query(
                exists().where(Conversation.id == conversation_id)
            ).scalar()

            if not conversation_exists:
                vdb_core.delete_by_query(
                    index_name,
                    {"term": {"conversation_id": conversation_id}}
                )
                db.query(ConversationFile).filter(
                    ConversationFile.conversation_id == conversation_id
                ).delete()
                logger.info(
                    "Cleaned up orphan chunks: index=%s, conversation=%s",
                    index_name, conversation_id
                )

    db.commit()
```

此任务是兜底机制，正常情况下数据在 conversation 删除时已被主动清理。

#### 4.2.7 delete_by_query 的注意事项

与 `delete_index` 相比，`delete_by_query` 有以下差异需要关注：

| 维度 | delete_index | delete_by_query |
|------|-------------|-----------------|
| 速度 | 瞬时（删元数据） | 较慢（遍历匹配文档） |
| 磁盘回收 | 立即 | 等 segment merge 后回收 |
| tombstone | 无 | 产生 deleted docs 标记 |

**应对措施**：
- 定时清理任务在低峰期执行，避免 delete_by_query 影响在线检索性能
- 配置 ES `index.merge.policy` 策略，定期 force merge 清理 tombstone
- 监控 `docs.deleted` 指标，必要时触发 `_forcemerge`

---

## 5. 详细实现方案

### 5.1 整体数据流

```
用户上传文件（现有流程）
  │
  ▼
MinIO 存储（现有）
  │
  ▼
create_agent_run_info() 入口
  │
  ├─ 判断文件类型
  │   ├─ 多媒体文件 → join_minio_file_description_to_query()（现有逻辑不变）
  │   └─ 文档文件 → prepare_fulltext_context()（新增）
  │
  ▼
prepare_fulltext_context()
  │
  ├─ 检查是否已处理（PG 查询 conversation_file_t）
  │   ├─ 已处理 → 跳过预处理
  │   └─ 未处理 → 统一处理流水线：
  │       ├─ 1. 提取全文 → 存 MinIO (fulltext_key)
  │       └─ 2. 分片 → embedding → 写入 ES (chunks)
  │
  ├─ 读取 Agent 当前 file_mode 配置，决定查询方式
  │
  ▼
Agent Run
  │
  ├─ file_mode = "full_text_reference"
  │   → 读 fulltext_key 拼入 context，LLM 直接回答
  │
  └─ file_mode = "chunk_search"
      → KnowledgeBaseSearchTool 检索文件问答索引 + 永久知识库
        │
        ▼
      Rerank（如果 Agent 配置了 rerank 模型）
        │
        ├─ 初始检索 rerank_top_n × RERANK_OVERSEARCH_MULTIPLIER 条候选
        ├─ rerank_model.rerank(query, candidates) 重排序
        └─ 取 rerank_top_n 条最终结果返回 LLM
```

### 5.2 新增模块

#### 5.2.1 `backend/services/conversation_file_service.py`（新增）

核心业务逻辑：

```python
"""
Conversation File Service

Handles document file processing for conversation-level Q&A.
Supports two modes: full-text reference and chunk search (RAG).
File metadata persists in PostgreSQL, lifecycle follows conversation.
"""

import hashlib
import io
import logging
import os
from typing import Dict, List, Optional, Tuple

from nexent.core.agents.agent_model import FilePreprocessConfig
from nexent.data_process.core import DataProcessCore

from database.attachment_db import delete_file, get_file_stream, upload_fileobj
from database.conversation_file_db import (
    create_conversation_file,
    delete_conversation_files,
    get_conversation_file_by_hash,
    get_conversation_files,
    update_conversation_file_status,
)

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS = {
    ".txt", ".pdf", ".docx", ".doc", ".html", ".htm", ".md", ".rtf",
    ".odt", ".pptx", ".ppt", ".json", ".epub", ".csv", ".xml",
    ".xlsx", ".xls",
}

FULLTEXT_CACHE_PREFIX = "conversation_file_cache"
CONVERSATION_FILE_INDEX_PREFIX = "conversation_file"


# --- File Type Detection ---

def is_document_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in DOCUMENT_EXTENSIONS


# --- Index Naming (Tenant-level shared index) ---

def build_index_name(tenant_id: str) -> str:
    return f"{CONVERSATION_FILE_INDEX_PREFIX}_{tenant_id}"


# --- Token Estimation ---

def estimate_tokens(text: str) -> int:
    return len(text) * 2 // 3


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return text
    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text
    char_limit = max_tokens * 3 // 2
    return text[:char_limit]


# --- Full-text Extraction ---

def extract_full_text(file_data: bytes, filename: str) -> str:
    processor = DataProcessCore()
    chunks, _ = processor.file_process(
        file_data=file_data,
        filename=filename,
        chunking_strategy="none",
    )
    return "\n\n".join(chunk.get("content", "") for chunk in chunks)


def compute_file_hash(file_data: bytes) -> str:
    return hashlib.sha256(file_data).hexdigest()


# --- Fulltext Context Building ---

def build_fulltext_context(
    file_texts: Dict[str, str],
    query: str,
    max_parse_length: int = 2000,
    prompt_max_token_length: int = 5000,
) -> str:
    file_sections = []
    for idx, (filename, text) in enumerate(file_texts.items(), 1):
        truncated = _truncate_to_tokens(text, max_parse_length)
        file_sections.append(
            f'<file name="{filename}" id="file_{idx}">\n{truncated}\n</file>'
        )

    joined = "\n\n".join(file_sections)
    joined = _truncate_to_tokens(joined, prompt_max_token_length)

    return (
        "<uploaded_files>\n\n"
        f"{joined}\n\n"
        "</uploaded_files>\n\n"
        "You have access to the user's uploaded files enclosed in <uploaded_files> tags.\n"
        "Rules:\n"
        "1. When answering, ALWAYS cite the source file using【file_name】format.\n"
        "2. If information comes from multiple files, cite each source separately.\n"
        "3. NEVER combine or merge facts from different files into a single unsourced statement.\n"
        "4. If files contain conflicting information, present both versions with their respective sources.\n\n"
        f"User question: {query}"
    )


# --- File Processing ---

def process_conversation_file(
    file_info: dict,
    conversation_id: str,
    tenant_id: str,
) -> Optional[dict]:
    object_name = file_info.get("object_name", "")
    filename = file_info.get("name", "")

    stream = get_file_stream(object_name)
    if stream is None:
        logger.error("Failed to download file from MinIO: %s", object_name)
        return None

    file_data = stream.read()
    content_hash = compute_file_hash(file_data)

    existing = get_conversation_file_by_hash(str(conversation_id), content_hash)
    if existing:
        logger.info("Duplicate file skipped: %s (hash=%s)", filename, content_hash[:12])
        return existing

    return _process_file_data(
        file_data, file_info, conversation_id, tenant_id, content_hash,
    )


def prepare_fulltext_context(
    minio_files: List[dict],
    query: str,
    conversation_id: str,
    tenant_id: str,
    file_preprocess_config: FilePreprocessConfig,
) -> Tuple[str, List[dict]]:
    """
    Process document files and build fulltext context.

    Returns:
        (modified_query, remaining_minio_files) where remaining_minio_files
        are non-document files that should still go through the existing
        join_minio_file_description_to_query path.
    """
    # ... separates doc/non-doc files, processes new docs, builds XML context
    # See actual implementation in conversation_file_service.py


# --- Conversation Cleanup ---

def cleanup_conversation_files(conversation_id: str) -> None:
    records = get_conversation_files(str(conversation_id))
    for r in records:
        if r.get("fulltext_key"):
            try:
                delete_file(r["fulltext_key"])
            except Exception as e:
                logger.warning("Failed to delete fulltext cache %s: %s", r["fulltext_key"], e)

    count = delete_conversation_files(str(conversation_id))
    if count > 0:
        logger.info("Cleaned up %d conversation file records for conversation %s", count, conversation_id)
```

#### 5.2.2 `backend/agents/create_agent_info.py` 改动

在 `create_agent_run_info()` 中增加文件问答处理分支：

```python
# --- 在 create_agent_run_info() 中，现有 join_minio_file_description_to_query 之前 ---

# File preprocessing: extract document content for fulltext reference
remaining_minio_files = minio_files
preprocessed_query = query
if conversation_id and minio_files:
    try:
        agent_info_for_preprocess = search_agent_info_by_agent_id(
            agent_id=agent_id, tenant_id=tenant_id, version_no=version_no,
        )
        file_preprocess_raw = agent_info_for_preprocess.get("file_preprocess") if agent_info_for_preprocess else None
        if file_preprocess_raw:
            from nexent.core.agents.agent_model import AgentFilePreprocessConfig
            fp_config = AgentFilePreprocessConfig.model_validate(file_preprocess_raw)
            if fp_config.enable and fp_config.config.file_mode == "full_text_reference":
                from services.conversation_file_service import prepare_fulltext_context
                preprocessed_query, remaining_minio_files = prepare_fulltext_context(
                    minio_files=minio_files,
                    query=query,
                    conversation_id=str(conversation_id),
                    tenant_id=tenant_id,
                    file_preprocess_config=fp_config.config,
                )
    except Exception as e:
        logger.warning("File preprocessing failed, falling back to default: %s", e)

final_query = await join_minio_file_description_to_query(
    minio_files=remaining_minio_files,
    query=preprocessed_query,
    history=history
)
```

#### 5.2.3 KnowledgeBaseSearchTool 的检索融合（切片检索模式，后续实现）

在 `create_agent_info.py` 构建 `KnowledgeBaseSearchTool` 时（约 line 1020）：

```python
# 现有代码
index_names = tool_config.params.get("index_names", [])

# 新增：追加会话文件共享索引
if conversation_file_info:
    conv_file_index_name, conv_file_conversation_id = conversation_file_info
    index_names = list(index_names) + [conv_file_index_name]
```

**关键适配**：会话文件的共享索引中混合了多个 conversation 的数据，检索时必须注入 `conversation_id` filter。实现方式有两种：

**方式 A（推荐）**：扩展 `KnowledgeBaseSearchTool` 的搜索方法，支持传入额外 filter 条件：

```python
# 在 _run_search 中，对 conversation_file_ 开头的索引自动注入 conversation_id filter
for idx in index_names:
    if idx.startswith("conversation_file_"):
        search_filter = {"term": {"conversation_id": conv_file_conversation_id}}
        # 将 filter 注入 ES query 的 bool.filter 中
```

**方式 B**：利用现有的 `_internal_document_paths` 机制，将当前会话文件的 `path_or_url` 列表传入做白名单过滤。但这要求事先知道所有已上传文件的 object_name，不如方式 A 通用。

两种索引使用相同的 embedding model（Agent 配置的），向量空间一致，混合检索的分数可比。

#### 5.2.4 Conversation 删除联动清理

在现有的 conversation 删除逻辑中增加会话文件数据清理，无需新增独立 API：

```python
# backend/services/conversation_management_service.py 中的 delete_conversation_service() 方法

# Clean up conversation file data (PG records + MinIO fulltext caches)
try:
    from services.conversation_file_service import cleanup_conversation_files
    cleanup_conversation_files(str(conversation_id))
except Exception as cleanup_err:
    logging.warning("Conversation file cleanup failed for conversation %s: %s", conversation_id, cleanup_err)
```

不再需要前端 `beforeunload` 调用清理 API — 文件数据跟随 conversation 自动管理。

### 5.3 异步处理流程与文件状态机

统一处理流水线中，分片+embedding 入库是耗时操作，使用异步处理。核心问题：**query 到达时文件可能还没处理完（全文未提取、chunk 未写入 ES）**。通过文件级状态机解决。

#### 5.3.1 文件状态机

每个文件在 PostgreSQL `conversation_file_t` 表中维护独立状态：

```
状态流转:

  pending ──→ parsing ──→ indexing ──→ ready
                │            │
                ▼            ▼
             failed       failed
```

PG 表中每个文件一条记录：

```
conversation_file_t 表示例:
  id=1, conversation_id="conv_abc", filename="report.pdf",  status="ready",    chunk_count=42, fulltext_key=NULL
  id=2, conversation_id="conv_abc", filename="spec.docx",   status="indexing", chunk_count=0,  fulltext_key=NULL
  id=3, conversation_id="conv_abc", filename="summary.md",  status="ready",    chunk_count=0,  fulltext_key="conversation_file_cache/xxx.txt"
  id=4, conversation_id="conv_abc", filename="data.csv",    status="failed",   chunk_count=0,  fulltext_key=NULL, error_message="parse error"
```

处理完成度通过字段推导：
- `fulltext_key` 不为空 → 全文提取完成
- `chunk_count > 0` → 分片入库完成
- 两者都有值且 `status="ready"` → 统一流水线完整完成

状态含义：

| 状态 | 含义 | query 到达时的行为 |
|------|------|------------------|
| `pending` | 已注册，等待处理 | 该文件暂不可用，跳过 |
| `parsing` | 正在解析/提取全文 | 该文件暂不可用，跳过 |
| `indexing` | 全文已提取，正在分片入库 ES | full_text_reference 可用（有 fulltext_key），chunk_search 暂不可用 |
| `ready` | 全部完成（全文 + chunks） | 两种模式都可用 |
| `failed` | 处理失败 | 降级：自定义处理模式（URL 拼入 prompt） |

#### 5.3.2 异步处理流程

```
用户上传文件并发送消息
  │
  ▼
prepare_fulltext_context()
  │
  ├─ 在 PG 中创建 conversation_file_t 记录，status = "pending"
  │
  ▼
启动异步任务 (PreprocessManager.register_preprocess_task)
  │
  ├─ update_conversation_file_status(record_id, "parsing")
  ├─ download_from_minio(object_name)
  ├─ DataProcessCore.file_process(file_data, filename)
  │
  ├─ Step A: 提取全文 → upload_to_minio(fulltext_key)
  ├─ update_conversation_file_status(record_id, "indexing", fulltext_key=key)
  │
  ├─ Step B: 分片 → embedding → ElasticSearchCore.vectorize_documents()
  ├─ update_conversation_file_status(record_id, "ready", chunk_count=N)
  │
  └─ 失败时: update_conversation_file_status(record_id, "failed", error_message="...")
```

#### 5.3.3 Query 到达时的决策逻辑

```python
def resolve_conversation_file_strategy(file_records: list, file_mode: str):
    """Decide how to answer based on file processing states and Agent's file_mode."""
    ready_files = [f for f in file_records if f.status == "ready"]
    indexing_files = [f for f in file_records if f.status == "indexing"]
    pending_files = [f for f in file_records if f.status in ("pending", "parsing")]
    failed_files = [f for f in file_records if f.status == "failed"]

    strategy = {
        "ready_files": ready_files,
        "pending_files": pending_files + indexing_files,
        "failed_files": failed_files,
    }

    if file_mode == "full_text_reference":
        # indexing 状态的文件 fulltext_key 已就绪，也可用于全文引用
        strategy["usable_files"] = ready_files + [
            f for f in indexing_files if f.fulltext_key
        ]
    else:  # chunk_search
        # 只有 ready 状态的文件有完整 chunks
        strategy["usable_files"] = ready_files

    return strategy
```

实际行为：

```
file_mode = "full_text_reference":
  情况1: 所有文件 ready 或 indexing(有 fulltext_key) → 全部可用
  情况2: 部分 pending/parsing → 可用的文件正常拼入，附注处理进度
  情况3: 文件 failed → 降级为自定义处理（URL 拼入 prompt）

file_mode = "chunk_search":
  情况1: 所有文件 ready → 正常 RAG 检索
  情况2: 部分 ready，部分 indexing/pending
    → ready 文件走 RAG 检索
    → 附注 "⏳ 部分文件仍在处理中，后续问答将获得更完整的检索结果"
  情况3: 所有文件都在处理中（首次上传的第一个 query）
    → 如果有 fulltext_key 可用，临时降级为全文引用
    → 否则跳过文件问答，附注处理进度
  情况4: 文件 failed → 降级为自定义处理（URL 拼入 prompt）
```

### 5.4 多轮文件累积

采用**自动累积**策略，与百炼行为一致（经测试验证）：

```
轮次1: 上传文件A → 处理A → 可问A的问题
轮次2: 不传文件  → A仍在索引/缓存中 → 可问A的问题
轮次3: 上传文件B → 处理B(增量append) → 可同时问A和B的问题
轮次4: 不传文件  → A和B都在 → 可交叉问答
```

实现方式：
- 每个文件统一做全文提取 + 分片入库，结果分别存 MinIO（fulltext_key）和 ES（chunks）
- 新文件的 chunks 追加 (append) 到同一个 ES 索引，不重建
- **跨会话恢复**：用户回到历史 conversation 时，PG 中的文件记录仍在，全文缓存在 MinIO，ES chunks 仍在索引中，无需重新处理
- **模式切换无感知**：管理员修改 Agent 的 `file_mode` 后，用户回到历史对话时，两种数据都已就绪，直接按新 `file_mode` 读取

### 5.5 文件去重

每次上传 MinIO 会生成不同的 `object_name`，不能用 `object_name` 做去重。使用 **content hash** 去重：

#### 5.5.1 去重流程

```python
import hashlib

def compute_file_hash(file_data: bytes) -> str:
    return hashlib.sha256(file_data).hexdigest()
```

```
新文件上传
  │
  ▼
计算 content_hash = sha256(file_data)
  │
  ▼
查 PG conversation_file_t 中已有文件的 hash
  │
  ├─ hash 不存在 → 新文件，正常处理
  │
  ├─ hash 存在 且 filename 相同 → 完全重复，跳过
  │
  └─ hash 存在 但 filename 不同 → 内容相同换了名字，跳过并提示
```

#### 5.5.2 同名文件但内容不同（文件更新）

用户可能上传同名文件的新版本（如修改后重新上传 `report.pdf`）：

```
新文件上传
  │
  ▼
filename 匹配到已有文件 但 hash 不同 → 视为文件更新
  │
  ├─ 删除旧数据：
  │   ├─ 删除 MinIO 中旧的 fulltext 缓存
  │   ├─ delete_by_query(conversation_id + old_object_name) 删除旧 ES chunks
  │   └─ 删除 PG 中旧记录
  │
  └─ 重新执行统一处理流水线（全文提取 + 分片入库）
```

#### 5.5.3 PG 中的文件记录

```
conversation_file_t 表:
  id=1, object_name="xxx", filename="report.pdf", content_hash="a1b2c3d4...", status="ready", chunk_count=42
```

去重判断优先级：`content_hash` > `filename` > `object_name`。

---

## 6. 与永久知识库的关系

### 6.1 差异对比

| 维度 | 永久知识库 | 文件问答共享索引 |
|------|----------|---------------|
| 生命周期 | 永久，用户手动管理 | 索引长期存在，数据随 conversation 删除而清理 |
| 索引命名 | 用户自定义 | `conversation_file_{tenant_id}`（每个租户 1 个） |
| 数据隔离 | 索引级隔离 | `conversation_id` 字段过滤 |
| 元数据存储 | PostgreSQL (`knowledge_db`) | PostgreSQL (`conversation_file_t`) |
| 文件来源 | 知识库管理页面上传 | 聊天中直接上传 |
| 检索范围 | Agent 绑定的知识库 | 当前会话上传的文件（conversation_id filter） |
| Embedding 模型 | 知识库自身配置 | Agent 配置的 embedding 模型 |

### 6.2 联合检索

当 Agent 同时配置了永久知识库和用户上传了会话文件时，`KnowledgeBaseSearchTool` 在单次搜索中**同时检索两者**：

```python
# index_names 合并示例
index_names = [
    "kb_product_docs",           # 永久知识库：产品文档
    "kb_faq",                    # 永久知识库：FAQ
    "conversation_file_tenant1",  # 会话文件共享索引（需注入 conversation_id filter）
]

# hybrid_search 在所有索引中统一检索，结果按 score 排序
# 对 conversation_file_ 索引自动注入 conversation_id filter
results = vdb_core.hybrid_search(
    index_names=index_names,
    query_text=query,
    embedding_model=embedding_model,
    top_k=5,
)
```

---

## 7. 前端改动

### 7.1 改动范围（最小化）

前端不需要新增 UI 组件，仅需以下小改动：

| 改动点 | 文件 | 内容 |
|--------|------|------|
| 文件处理状态提示 | `chatStreamHandler.tsx` | 展示 "文件处理中..." / "文件处理完成" 的 streaming token |
| 模式配置（可选） | Agent 配置页 | 在 Agent 高级设置中添加"文件问答"开关（可选，默认开启） |

**注意**：无需 `beforeunload` 清理逻辑，文件数据跟随 conversation 生命周期自动管理。

### 7.2 前端无需改动的部分

- 文件上传 UI：已有 `chatAttachment.tsx`
- 文件预览：已有 `FilePreviewDrawer`
- 文件类型校验：已有 `uploadService.ts`

---

## 8. 改动清单

### 8.1 新增文件

| 文件 | 作用 |
|------|------|
| `backend/services/conversation_file_service.py` | 会话文件核心业务逻辑（全文提取、分片入库、文件记录管理、清理） |
| `backend/database/conversation_file_db.py` | `conversation_file_t` 表的 SQLAlchemy ORM 模型及 CRUD |
| `deploy/sql/migrations/v2.3.0_0714_add_conversation_file.sql` | 数据库迁移脚本，创建 `conversation_file_t` 表 |

### 8.2 修改文件

| 文件 | 改动内容 |
|------|---------|
| `backend/agents/create_agent_info.py` | 在 `create_agent_run_info()` 中调用 `prepare_fulltext_context()`，将文件内容注入 context 或追加临时索引到 `index_names` |
| `backend/services/conversation_management_service.py` | conversation 删除时联动调用 `cleanup_conversation_files()` 清理会话文件数据 |
| `frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx` | 处理文件处理状态的 streaming token |

### 8.3 不修改的文件

| 文件 | 原因 |
|------|------|
| `sdk/nexent/data_process/*` | 直接复用 `DataProcessCore.file_process()` |
| `sdk/nexent/vector_database/*` | 直接复用 `ElasticSearchCore` 全套接口 |
| `sdk/nexent/core/tools/knowledge_base_search_tool.py` | 不改工具本身，只在构建时追加 index_names |
| `sdk/nexent/core/tools/analyze_*_tool.py` | 多媒体处理已覆盖，不需要改动 |
| `frontend/lib/chat/chatAttachmentUtils.ts` | 上传流程不变 |
| `frontend/services/storageService.ts` | 存储服务不变 |
| `frontend/hooks/chat/useConversationManagement.ts` | 无需 beforeunload 清理，不改动 |

---

## 9. 注意事项

### 9.1 Embedding 模型一致性

文件问答的 embedding model 取自 `index_names[0]`（第一个知识库）的配置，与现有知识库 RAG 检索行为保持一致。

`conversation_file_t` 表的 `embedding_model` 字段记录每个文件入库时使用的模型标识，但**本期不做模型变更检测和自动重建**。原因：
- 现有知识库 RAG 也不处理多知识库 embedding model 不一致的问题（查询时统一用第一个知识库的模型）
- 文件问答如果单独做检测+重建，会与知识库行为产生割裂
- `embedding_model` 字段预留给后续统一治理——未来知识库和文件问答一起升级模型一致性检查

### 9.2 文件大小限制

- 单文件上限：与现有 MinIO 上传限制一致
- 单会话文件数：建议限制 10 个文档文件（与百炼一致）
- 全文引用模式的文本总量：受模型上下文窗口限制（自动选择时已考虑）

### 9.3 并发安全

- 同一 conversation 的多个请求可能并发触发分片入库
- 通过 PG `content_hash` 唯一约束 + 去重逻辑防止重复处理同一文件
- ES `vectorize_documents` 本身是幂等的（相同 content 写入不会产生冲突）

### 9.4 错误处理

- 文件解析失败：跳过该文件，其余文件正常处理，返回部分结果
- ES 索引创建失败：降级为自定义处理模式（URL 拼入 prompt）
- Embedding API 超时：重试 1 次，仍失败则降级为全文引用（截断文本）

---

## 10. 后续优化项（本期不实现）

### 10.1 Query Rewrite（查询改写）

**现状**：Nexent 的 `KnowledgeBaseSearchTool` 没有 query rewrite 能力。仅 `AidpSearchTool` 有 `rewrite_enable` 参数，但改写逻辑在远端 AIDP 服务，非 Nexent 自有实现。

**为什么本期可以不做**：Nexent 的 Agent 架构天然有一层缓解——LLM 作为 Agent 调用 `KnowledgeBaseSearchTool` 时，会自行构造 `query` 参数而非直接使用用户原文，相当于 Agent 本身承担了部分 query rewrite 的角色。

**后续优化价值**：
- **多轮指代消解**：用户说"它的第三章讲了什么"，需结合 history 改写为"《产品需求文档.pdf》第三章的内容"，当前 Agent 不一定能稳定做到
- **口语化 → 检索友好**：如"这俩报告利润差多少" → "Q3财报 净利润 Q2财报 净利润"
- **多意图拆分**：一个问题包含多个检索意图时拆分为多次检索

**建议实现方式**：在 `KnowledgeBaseSearchTool.forward()` 内部、检索前增加一步 LLM 调用做 query rewrite，输入 `(original_query, history)`，输出改写后的检索 query。

### 10.2 检索结果缓存

**现状**：每次 query 都执行完整的 embedding + ES search 链路，无缓存命中机制。

**为什么本期可以不做**：query 侧开销较小（1 次单条 embedding 调用 + 1 次 ES search，总耗时通常 < 100ms），与入库时对所有 chunk 做 embedding 的成本不在一个量级。对用户体感影响有限。

**后续优化价值**：
- **完全相同 query**：多轮对话中 Agent 可能对同一 query 重复调用 tool（retry、思考链中的重复检索），可直接命中缓存
- **语义相似 query**：用户换个说法问同一件事，避免重复检索
- **降低 embedding API 调用量**：高并发场景下减少外部 API 压力

**建议实现方式**：

```
层级1（简单，建议优先）：Query Hash 精确缓存
  - key: hash(query_text + index_names + search_mode + top_k)
  - value: 检索结果 JSON
  - 存储: 内存 dict 或 Redis，TTL 300s（会话内有效）
  - 命中条件: query 完全一致

层级2（进阶）：语义相似缓存
  - 缓存 query embedding，新 query 先与缓存中的 embedding 算余弦相似度
  - 相似度 > 0.95 → 命中缓存，跳过 ES search
  - 需权衡：额外的相似度计算 vs 省下的 ES search，小索引场景收益不大
```
