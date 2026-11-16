# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Active Management imports of Infrastructure-owned knowledge records."""

from infrastructure.rdb.knowledge_file_record import (
    KnowledgeFileLifecycle as KnowledgeFileLifecycle,  # noqa: PLC0414 - Active Management export.
)
from infrastructure.rdb.knowledge_search_records import (
    KnowledgeRecord as KnowledgeRecord,  # noqa: PLC0414 - Active Management export.
)
from infrastructure.rdb.knowledge_storage_record import (
    KnowledgeStorageObject as KnowledgeStorageObject,  # noqa: PLC0414 - Active Management export.
)
