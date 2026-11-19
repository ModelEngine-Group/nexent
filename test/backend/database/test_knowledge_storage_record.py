# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep the unchanged source-ledger schema constraint and index regression."""

from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject


def test_model_has_identity_constraint_and_active_indexes():
    table = KnowledgeStorageObject.__table__
    unique = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert table.schema == "nexent"
    assert unique["uq_knowledge_storage_object_bucket_object"] == (
        "bucket_name",
        "object_name",
    )
    assert {index.name for index in table.indexes} == {
        "idx_knowledge_storage_object_tenant_active",
        "idx_knowledge_storage_object_kb_active",
    }
    kb_index = next(
        index
        for index in table.indexes
        if index.name == "idx_knowledge_storage_object_kb_active"
    )
    assert [column.name for column in kb_index.columns] == ["tenant_id", "knowledge_id"]
