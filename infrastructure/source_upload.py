# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite, process-local storage bindings for one preallocated KB source upload."""

import logging
from contextlib import contextmanager
from math import ceil

from nexent.storage.errors import OutcomeUnknown
from nexent.storage.models import StorageScope
from sqlalchemy import URL, create_engine

from infrastructure.object_storage.composition import bind_source_objects
from infrastructure.rdb.source_binding import DATASET, bind_source_records


@contextmanager
def source_upload_ports(record, *, context):
    from contracts.constants import environment

    remaining = context.remaining()
    engine = create_engine(
        URL.create(
            "postgresql+psycopg2",
            username=environment.POSTGRES_USER,
            password=environment.NEXENT_POSTGRES_PASSWORD,
            host=environment.POSTGRES_HOST,
            port=int(environment.POSTGRES_PORT),
            database=environment.POSTGRES_DB,
        ),
        connect_args={"connect_timeout": max(1, ceil(min(5, remaining)))},
        pool_size=1,
        max_overflow=0,
        pool_timeout=min(5, remaining),
        hide_parameters=True,
    )
    records = objects = None
    try:
        scope = StorageScope(
            "management", record["tenant_id"], record["created_by"], {DATASET}
        )
        records = bind_source_records(scope, engine)
        objects = bind_source_objects(
            record["tenant_id"],
            record["created_by"],
            record["object_name"],
            record["bucket_name"],
        )
        yield records, objects
    finally:
        failed = False
        cleanup = [engine.dispose]
        if records is not None:
            cleanup.insert(0, records.close)
        if objects is not None:
            cleanup.insert(0, objects.close)
        for close in cleanup:
            try:
                close()
            except Exception as error:  # noqa: BLE001 - Finish every owned cleanup and preserve uncertainty.
                failed = True
                logging.getLogger(__name__).warning(
                    "source_upload_cleanup_failed error_type=%s", type(error).__name__
                )
        if failed:
            raise OutcomeUnknown(operation_id=context.operation_id) from None
