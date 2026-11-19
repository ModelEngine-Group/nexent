# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read bounded AgentOS quota statistics with pinned resources and actual identity."""

import logging

from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeUpstreamError
from contracts.knowledge_collections import (
    KnowledgeCollectionsUsage,
    KnowledgeCollectionsUsageResult,
)
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)

from infrastructure.knowledge_search import knowledge_search_revision

logger = logging.getLogger(__name__)


async def collection_usage_statistics(client, actor, rows, context, *, include_datamate=False):
    selected = [row for row in rows if row.get('index_name') and (include_datamate or row.get('knowledge_sources') != 'datamate')]
    observed = {}
    for start in range(0, len(selected), 100):
        context.remaining()
        batch = selected[start:start + 100]
        expected = {row['knowledge_id']: knowledge_search_revision(row) for row in batch}
        if len(expected) != len(batch):
            raise Conflict()
        try:
            response = await client.knowledge_collection_usage(KnowledgeCollectionsUsage(
                knowledge_ids=list(expected), expected_revisions=expected), actor.user_id, actor.tenant_id)
        except RuntimeUpstreamError as error:
            kind = {403: ScopeDenied, 409: Conflict}.get(error.status_code)
            if kind is not None:
                raise kind(operation_id=context.operation_id) from error
            logger.warning('tenant_quota_statistics_unavailable operation_id=%s exception_type=%s',
                           context.operation_id, type(error).__name__)
            continue
        except RuntimeServiceTimeoutError:
            # The AgentOS client already logs its bounded transport timeout.
            context.remaining()
            continue
        except (DeadlineExceeded, OperationCancelled, ScopeDenied, Conflict):
            raise
        except Exception as error:  # noqa: BLE001 - Preserve optional ES observability failure.
            logger.warning('tenant_quota_statistics_unavailable operation_id=%s exception_type=%s',
                           context.operation_id, type(error).__name__)
            continue
        if not isinstance(response, KnowledgeCollectionsUsageResult) or (
            [item.knowledge_id for item in response.items] != list(expected)
            or any(item.expected_revision != expected[item.knowledge_id] for item in response.items)
        ):
            raise Conflict()
        observed.update((item.knowledge_id, item.statistics) for item in response.items)
    context.remaining()
    return observed
