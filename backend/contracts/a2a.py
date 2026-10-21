# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class A2AExecutionContext:
    """Context for A2A task execution."""

    task_id: str
    endpoint_id: str
    token_id: Optional[int] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_debug: bool = False
