# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ops-to-management import surface guard.

The ops container is decoupled from management by a curated module surface:
whatever ops imports from management ships in the ops image and becomes a
cross-service coupling. This test freezes that surface to the develop
baseline so a new import fails here instead of silently deepening the
coupling (or crashing the container, which the image whitelist test covers).
Additions require a decoupling review: put the primitive in the shared Web
layer (backend/http/server) or the shared storage adapters (infrastructure)
instead.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OPS_TREE = ROOT / "backend" / "ops"

_IMPORT = re.compile(r"^\s*(?:from|import)\s+(management(?:\.\w+)+)")

# The develop baseline: every management module ops imported before the
# northbound monitoring work. Sorted; extend only after a decoupling review.
DEVELOP_BASELINE = {
    "management.api.permission.ops_access",
    "management.db.agent.models",
    "management.db.configuration.models",
    "management.db.conversation.classification",
    "management.db.conversation.models",
    "management.db.identity.conversation_agent_history_db",
    "management.db.identity.models",
    "management.db.model.models",
    "management.services.configuration.resource_denylist",
    "management.services.permission.identity.session",
    "management.utils.serialization",
}


def test_ops_management_imports_stay_within_the_develop_surface():
    imported = set()
    for path in sorted(OPS_TREE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _IMPORT.match(line)
            if match:
                imported.add(match.group(1))
    unexpected = imported - DEVELOP_BASELINE
    assert not unexpected, (
        "backend/ops imports management modules beyond the develop baseline "
        "(cross-service coupling; move the primitive to the shared Web layer "
        f"or infrastructure instead): {sorted(unexpected)}"
    )
    # A dropped import is fine; a baseline entry that no longer exists would
    # make the set stale, so keep the guard honest about drift.
    assert DEVELOP_BASELINE, "baseline must stay pinned"
