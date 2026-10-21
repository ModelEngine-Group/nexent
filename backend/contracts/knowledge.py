# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from contracts.models import ToolParamsRequest


@dataclass
class ResolvedKnowledgeScope:
    """Runtime projection of a persisted conversation knowledge policy."""

    desired_scope: Dict[str, Any]
    tool_params: ToolParamsRequest
    local_knowledge_ids: List[str] = field(default_factory=list)
    local_index_names: List[str] = field(default_factory=list)
    local_display_names: List[str] = field(default_factory=list)
    aidp_kds_ids: List[str] = field(default_factory=list)
    aidp_display_names: List[str] = field(default_factory=list)
    local_disabled: bool = False
    aidp_disabled: bool = False
    local_capable: bool = True
    aidp_capable: bool = True
    warnings: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeStorageContext:
    """Validated ownership and object-bucket context for one KB upload."""

    tenant_id: str
    knowledge_id: int
    index_name: str
    bucket_name: str
    ingroup_permission: Optional[str] = None


@dataclass(frozen=True)
class StorageObjectReference:
    """Canonical MinIO object identity for an existing KB source path."""

    bucket_name: str
    object_name: str


@dataclass(frozen=True)
class ClassifiedIngestionException:
    """A durable error representation plus retry guidance for the active task."""

    error_code: Optional[str]
    error_message: Optional[str]
    retryable: bool
