# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own read handles; resource-tenant handles are opened only after Management DAC."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_file_read import (
    bind_file_reads,
    bind_readable_knowledge,
)


@contextmanager
def knowledge_file_read_ports(actor, *, context):
    engine, owned = record_engine(context), []
    try:
        knowledge = bind_readable_knowledge(actor, engine)
        owned.append(knowledge)
        identity = bind_cleanse_resources(
            StorageScope(
                "management",
                actor.tenant_id,
                actor.user_id,
                {
                    "cleanse_memberships",
                    "cleanse_accounts",
                    "cleanse_group_memberships",
                    "cleanse_groups",
                },
            ),
            engine,
        )
        owned.append(identity)

        def scoped_files(tenant_id):
            records = bind_file_reads(tenant_id, actor.user_id, engine)
            owned.append(records)
            return records

        yield knowledge, identity, scoped_files
    finally:
        close_owned(
            context, [record.close for record in reversed(owned)] + [engine.dispose]
        )
