# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Create the Management directory before authorized AgentOS collection setup."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import ModelVersion
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionEnsure,
    KnowledgeCollectionEnsured,
)
from contracts.roles import has_any_role
from management.services.knowledge_base.catalog_policy import enforce_catalog_creation
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import FieldPatch, OperationContext, Revision, WriteOutcome

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient
from infrastructure.knowledge_catalog import CATALOG, knowledge_catalog_ports

logger = logging.getLogger(__name__)


def _create_directory(name, model, actor, values, ports, *, context):
    with ports(actor, context=context, writable=True, knowledge_name=name) as records:
        scope = records.scope
        if (scope.service_role != 'management' or scope.tenant_id != actor.tenant_id
            or scope.actor_id != actor.user_id or scope.system or scope.resource_prefix):
            raise ScopeDenied()
        with records.transaction(context=context) as tx:
            enforce_catalog_creation(tx, actor, name, context)
            row = tx.create(CATALOG, {'knowledge_name': name, 'knowledge_describe': '',
                'knowledge_sources': 'elasticsearch', 'embedding_model_id': model.model_id,
                'embedding_model_name': model.display_name or model.model_name, **values}, context=context)
            index_name = f"{row['knowledge_id']}-{uuid4().hex}"
            receipt = tx.patch(CATALOG, row['knowledge_id'], FieldPatch(set_values={'index_name': index_name}),
                               expected=Revision(str(row['version'])), context=context)
            if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
                # This transaction has not committed; its owner rolls it back.
                raise Conflict()
            return {**row, 'index_name': index_name}


async def create_knowledge_base(knowledge_name, actor, *, embedding_model_id, embedding_dim=None,
    ingroup_permission=None, group_ids=None, preserve_source_file=None, quota_limit_bytes=None, user_role=None,
    ports=knowledge_catalog_ports, reader=None, client=None, context=None, operation_seconds=180):
    if not isinstance(knowledge_name, str) or not knowledge_name.strip():
        raise ValueError('Knowledge base name is required')
    if type(embedding_model_id) is not int or embedding_model_id <= 0:
        raise ValueError('embedding_model_id is required')
    if type(operation_seconds) not in {int, float} or not 0 < operation_seconds <= 180:
        raise InvalidInput()
    if embedding_dim is not None and (type(embedding_dim) is not int or not 0 < embedding_dim <= 2**31 - 1):
        raise InvalidInput()
    name = knowledge_name.strip()
    cancelled = Event() if context is None else None
    context = context or OperationContext('knowledge-base-create-' + uuid4().hex,
                                         monotonic() + operation_seconds, cancelled=cancelled)
    client = client or AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client)
    reader = reader or KnowledgeFileReader()
    threshold = context.remaining()
    try:
        async with asyncio.timeout(threshold):
            try:
                model = await client.get_model(embedding_model_id, actor.user_id, actor.tenant_id)
            except RuntimeUpstreamError as error:
                if error.status_code == 404:
                    raise ValueError(f'Embedding model with id {embedding_model_id} not found') from error
                raise
            if not isinstance(model, ModelMetadata) or model.model_id != embedding_model_id:
                raise InvalidInput()
            if model.model_type not in {'embedding', 'multi_embedding'}:
                raise ValueError(f'Model with id {embedding_model_id} is not an embedding model')
            dimensions = embedding_dim if embedding_dim is not None else model.embedding_dimensions
            if type(dimensions) is not int or not 0 < dimensions <= 2**31 - 1:
                raise InvalidInput()
            values = {'preserve_source_file': True if preserve_source_file is None else preserve_source_file}
            if has_any_role(user_role, {'USER'}) and not has_any_role(user_role, {'DEV', 'ADMIN', 'SU', 'ASSET_OWNER'}):
                values.update(ingroup_permission='PRIVATE', group_ids=None)
            else:
                if ingroup_permission is not None:
                    values['ingroup_permission'] = ingroup_permission
                if group_ids is not None:
                    values['group_ids'] = ','.join(str(value) for value in group_ids) if isinstance(group_ids, list) else group_ids
            if quota_limit_bytes is not None:
                values['quota_limit_bytes'] = quota_limit_bytes
            row = await run_blocking('knowledge-base-catalog-create', _create_directory, name, model, actor, values, ports,
                                    context=context, lane='control-io', owner='management.knowledge_base')
            current = await run_blocking('knowledge-base-created-resource', reader.knowledge, row['index_name'], actor,
                                        edit=True, context=context, lane='control-io', owner='management.knowledge_base')
            if (current['knowledge_id'] != row['knowledge_id'] or current['index_name'] != row['index_name']
                or current['tenant_id'] != actor.tenant_id or current['embedding_model_id'] != model.model_id):
                raise Conflict()
            grant = chunks_resource_grant(current)
            result = await client.ensure_knowledge_collection(KnowledgeCollectionEnsure(
                knowledge_id=grant.knowledge_id, expected_revision=grant.revision, dimensions=dimensions,
                native_documents=environment.KNOWLEDGE_RUNTIME_HYBRID_ENABLED,
                model_binding=ModelVersion(model_id=model.model_id, revision=model.revision)), actor.user_id, actor.tenant_id)
            context.remaining()
            if (not isinstance(result, KnowledgeCollectionEnsured) or result.knowledge_id != grant.knowledge_id
                or result.expected_revision != grant.revision or result.dimensions != dimensions or result.present is not True):
                raise Conflict()
            return {'status': 'success', 'message': f"Index {row['index_name']} created successfully",
                'id': row['index_name'], 'knowledge_id': row['knowledge_id'], 'name': row['knowledge_name'],
                'embedding_model_name': model.display_name or model.model_name, 'model_type': model.model_type}
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        logger.warning('knowledge_base_create_timeout operation_id=%s threshold_seconds=%s exception_type=%s',
                       context.operation_id, threshold, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        if cancelled is not None:
            cancelled.set()
