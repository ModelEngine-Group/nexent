# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the existing DataMate URL without loading other tenant configuration."""

import logging
from dataclasses import replace
from threading import Event
from time import monotonic
from uuid import uuid4

from nexent.storage.errors import Conflict, DeadlineExceeded
from nexent.storage.models import OperationContext, PageRequest, RecordQuery, Sort

logger = logging.getLogger(__name__)


def datamate_configuration_url(tenant_id, *, ports=None, context=None):
    if not tenant_id:
        return ""
    from infrastructure.datamate_configuration import (
        DATASET,
        datamate_configuration_ports,
    )

    cancelled = Event()
    context = context or OperationContext(
        "datamate-config-" + uuid4().hex, monotonic() + 10, cancelled=cancelled
    )
    context = replace(context, deadline=min(context.deadline, monotonic() + 10))
    threshold = max(0, context.deadline - monotonic())
    try:
        context.remaining()
        with (ports or datamate_configuration_ports)(
            tenant_id, context=context
        ) as records:
            value, cursor, seen = "", None, set()
            while True:
                page = records.query(
                    DATASET,
                    RecordQuery(order_by=(Sort("tenant_config_id"),)),
                    PageRequest(limit=500, cursor=cursor),
                    context=context,
                )
                for row in page.items:
                    value = row["config_value"]
                context.remaining()
                if page.next_cursor is None:
                    return value
                if page.next_cursor in seen:
                    raise Conflict()
                seen.add(page.next_cursor)
                cursor = page.next_cursor
    except DeadlineExceeded as error:
        logger.warning(
            "datamate_configuration_timeout operation_id=%s phase=read threshold_seconds=%s exception_type=%s",
            context.operation_id,
            threshold,
            type(error).__name__,
        )
        raise
    finally:
        cancelled.set()
