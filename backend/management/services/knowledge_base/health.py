# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve public provider health semantics through bounded read-only ports."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

import httpx
from contracts.errors.exceptions import RuntimeServiceTimeoutError
from contracts.knowledge import VectorDatabaseType
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, OperationCancelled, StorageError
from nexent.storage.models import OperationContext

from infrastructure.collection_inventory import collection_inventory_ports

logger = logging.getLogger(__name__)


def health_result(db_type=VectorDatabaseType.ELASTICSEARCH, tenant_id=None, *, context=None,
                  ports=collection_inventory_ports):
    context = context or OperationContext('knowledge-health-' + uuid4().hex, monotonic()+30)
    context.remaining()
    if db_type == VectorDatabaseType.DATAMATE:
        from management.services.knowledge_base.providers.configuration import (
            datamate_configuration_url,
        )

        from infrastructure.vdb.datamate_inventory import datamate_collection_count

        if not tenant_id:
            raise ValueError('tenant_id must be provided for DataMate')
        try:
            url = datamate_configuration_url(tenant_id, context=context)
        except DeadlineExceeded as error:
            # Configuration already reports its own shorter read deadline.
            raise RuntimeServiceTimeoutError(str(error)) from error
        if not url:
            raise ValueError(f'DataMate URL not configured for tenant {tenant_id}')
        try:
            count = datamate_collection_count(url, context=context)
        except (DeadlineExceeded, OperationCancelled, httpx.TimeoutException):
            raise
        except Exception as error:
            raise RuntimeError(f'Health check failed: {error}') from error
    else:
        with ports(context=context) as inventory:
            try:
                count = inventory.count(context=context)
            except (DeadlineExceeded, OperationCancelled):
                raise
            except StorageError as error:
                # The old ES adapter logged query failures and returned an empty list.
                logger.error('knowledge_health_inventory_failed exception_type=%s', type(error).__name__)
                count = 0
            except Exception as error:
                raise RuntimeError(f'Health check failed: {error}') from error
    context.remaining()
    return {'status': 'healthy', 'elasticsearch': 'connected', 'indices_count': count}


async def check_knowledge_health(db_type=VectorDatabaseType.ELASTICSEARCH, tenant_id=None):
    cancelled = Event()
    context = OperationContext('knowledge-health-' + uuid4().hex, monotonic()+30, cancelled=cancelled)
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking('knowledge-health', health_result, db_type, tenant_id, context=context,
                                      lane='control-io', owner='management.knowledge.health')
    except (TimeoutError, DeadlineExceeded, httpx.TimeoutException) as error:
        provider_timeout = isinstance(error, httpx.TimeoutException)
        logger.warning('knowledge_health_timeout operation_id=%s phase=%s threshold_seconds=%s exception_type=%s',
                       context.operation_id, 'datamate_request' if provider_timeout else 'count',
                       5 if provider_timeout else 30, type(error).__name__)
        raise DeadlineExceeded(operation_id=context.operation_id) from error
    finally:
        cancelled.set()
