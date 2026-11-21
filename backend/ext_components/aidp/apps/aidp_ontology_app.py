# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


"""AIDP ontology management HTTP surface.

The routes are split by resource into sibling modules; this aggregator keeps the
single ``aidp_ontology_router`` entry point (and therefore every public path)
unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter

from ext_components.aidp.apps.aidp_ontology_batch_routes import (
    aidp_ontology_batch_router,
)
from ext_components.aidp.apps.aidp_ontology_binding_routes import (
    aidp_ontology_binding_router,
)
from ext_components.aidp.apps.aidp_ontology_domain_routes import (
    aidp_ontology_domain_router,
)
from ext_components.aidp.apps.aidp_ontology_metadata_routes import (
    aidp_ontology_metadata_router,
)
from ext_components.aidp.apps.aidp_ontology_rule_routes import (
    aidp_ontology_rule_router,
)
from ext_components.aidp.apps.aidp_ontology_task_routes import (
    aidp_ontology_task_router,
)


aidp_ontology_router = APIRouter(prefix="/aidp-mgmt/ontology", tags=["aidp-ontology"])
for _resource_router in (
    aidp_ontology_domain_router,
    aidp_ontology_binding_router,
    aidp_ontology_metadata_router,
    aidp_ontology_rule_router,
    aidp_ontology_task_router,
    aidp_ontology_batch_router,
):
    aidp_ontology_router.include_router(_resource_router)
