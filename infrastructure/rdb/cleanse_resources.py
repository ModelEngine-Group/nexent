# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only, credential-free resource catalogs for Management cleansing authorization."""

from nexent.storage.errors import ScopeDenied
from sqlalchemy import select

from infrastructure.rdb.account_record import (
    TenantGroupInfo,
    TenantGroupUser,
    UserAccount,
    UserTenant,
)
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_search_records import KnowledgeRecord
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

accounts = UserAccount.__table__
members = UserTenant.__table__
group_links = TenantGroupUser.__table__
groups = TenantGroupInfo.__table__
TABLES = {
    "cleanse_files": KnowledgeFileLifecycle.__table__,
    "knowledge_file_history": KnowledgeFileLifecycle.__table__,
    "cleanse_knowledge": KnowledgeRecord.__table__,
    "cleanse_memberships": UserTenant.__table__,
    "cleanse_accounts": select(
        accounts.c.account_id,
        accounts.c.user_id,
        accounts.c.user_roles,
        accounts.c.delete_flag,
        members.c.tenant_id,
    )
    .select_from(accounts.join(members, accounts.c.user_id == members.c.user_id))
    .where(members.c.delete_flag == "N")
    .subquery("cleanse_accounts"),
    "cleanse_group_memberships": select(
        group_links.c.group_user_id,
        group_links.c.user_id,
        group_links.c.group_id,
        group_links.c.delete_flag,
        groups.c.tenant_id,
    )
    .select_from(group_links.join(groups, group_links.c.group_id == groups.c.group_id))
    .where(groups.c.delete_flag == "N")
    .subquery("cleanse_group_memberships"),
    "cleanse_groups": TenantGroupInfo.__table__,
}
FIELDS = {
    "cleanse_files": "file_id tenant_id knowledge_id original_filename status source_generation source_space source_key source_revision source_sha256 bucket_name object_name delete_flag",
    "cleanse_knowledge": "knowledge_id tenant_id index_name embedding_model_id created_by group_ids ingroup_permission knowledge_sources delete_flag",
    "cleanse_memberships": "user_tenant_id user_id tenant_id delete_flag",
    "cleanse_accounts": "account_id tenant_id user_id user_roles delete_flag",
    "cleanse_group_memberships": "group_user_id tenant_id user_id group_id delete_flag",
    "cleanse_groups": "group_id tenant_id delete_flag",
}
FIELDS["knowledge_file_history"] = FIELDS["cleanse_files"]
INTEGER_FIELDS = {
    "embedding_model_id",
    "knowledge_id",
    "source_generation",
    "user_tenant_id",
    "account_id",
    "group_user_id",
    "group_id",
}


def bind_cleanse_resources(scope, engine):
    if not scope.namespaces <= set(TABLES):
        raise ScopeDenied()
    tables = {name: table for name, table in TABLES.items() if name in scope.namespaces}
    definitions = []
    for name, table in tables.items():
        fields = tuple(
            FieldDefinition(
                field,
                "integer"
                if field in INTEGER_FIELDS
                else "array"
                if field == "user_roles"
                else "string",
                nullable=table.c[field].nullable,
            )
            for field in FIELDS[name].split()
        )
        definitions.append(
            DatasetDefinition(
                name,
                next(
                    iter(
                        table.primary_key.columns
                        if hasattr(table.primary_key, "columns")
                        else table.primary_key
                    )
                ).name,
                fields,
                frozenset({"management"}),
                tenant_field="tenant_id" if "tenant_id" in table.c else None,
                active_field=None if name == "knowledge_file_history" else "delete_flag",
            )
        )
    return SQLRecordStore(
        scope, DatasetCatalog(tuple(definitions)), tables, engine, revision_fields={}
    )
