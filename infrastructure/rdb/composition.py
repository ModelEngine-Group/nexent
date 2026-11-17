# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded process-owned record engines and complete cleanup of owned handles."""

import logging
from math import ceil

from nexent.storage.errors import InvalidInput, OutcomeUnknown
from sqlalchemy import URL, create_engine


def record_engine(context, *, snapshot=False, connections=1):
    from contracts.constants import environment

    if type(connections) is not int or connections not in (1, 2):
        raise InvalidInput()
    remaining = context.remaining()
    return create_engine(
        URL.create(
            "postgresql+psycopg2",
            username=environment.POSTGRES_USER,
            password=environment.NEXENT_POSTGRES_PASSWORD,
            host=environment.POSTGRES_HOST,
            port=int(environment.POSTGRES_PORT),
            database=environment.POSTGRES_DB,
        ),
        connect_args={"connect_timeout": max(1, ceil(min(5, remaining)))},
        pool_size=connections,
        max_overflow=0,
        pool_timeout=min(5, remaining),
        hide_parameters=True,
        isolation_level="REPEATABLE READ" if snapshot else "READ COMMITTED",
    )


def close_owned(context, callbacks):
    failed = False
    for close in callbacks:
        try:
            close()
        except Exception as error:  # noqa: BLE001 - Close every owner even after one cleanup fails.
            failed = True
            logging.getLogger(__name__).warning(
                "record_resource_cleanup_failed error_type=%s", type(error).__name__
            )
    if failed:
        raise OutcomeUnknown(operation_id=context.operation_id) from None
