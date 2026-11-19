# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only vectors granted by the current reader's standard chunk authorization."""

from contextlib import contextmanager

from contracts.agentos_knowledge import KnowledgeChunksGrant
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.errors import ScopeDenied

from infrastructure.knowledge_vectors import bind_knowledge_vectors
from infrastructure.rdb.composition import close_owned


@contextmanager
def knowledge_source_ports(actor, grant, *, context):
    if not isinstance(grant, KnowledgeChunksGrant) or grant.resource_tenant_id not in {
        actor.tenant_id,
        ASSET_OWNER_TENANT_ID,
    }:
        raise ScopeDenied()
    context.remaining()
    vectors = bind_knowledge_vectors(
        actor,
        grant.collection,
        None,
        writable=False,
        resource_tenant_id=grant.resource_tenant_id,
    )
    try:
        yield vectors
    finally:
        close_owned(context, [vectors.close])
