# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep real configuration contracts available to legacy SDK namespace loaders."""

import sys

from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile  # noqa: F401
from nexent.core.models.capacity_budget import ContextBudgetSnapshot  # noqa: F401

# Older agent tests replace SDK package roots with dependency doubles. These
# two pure contracts must retain their real definitions under either namespace.
for _name, _module in list(sys.modules.items()):
    if _name.startswith("nexent.core.model_service") or _name.startswith("nexent.core.models.capacity_"):
        sys.modules.setdefault(f"sdk.{_name}", _module)
