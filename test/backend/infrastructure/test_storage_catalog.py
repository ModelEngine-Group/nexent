# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SI-001/002/011: logical queries cannot override catalog scope policies."""

import pytest
from nexent.storage.errors import CapabilityUnsupported, InvalidInput, ScopeDenied
from nexent.storage.models import Comparison, Junction, RecordQuery, Sort, StorageScope

from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


@pytest.fixture
def catalog():
    return DatasetCatalog(
        (
            DatasetDefinition(
                name="documents",
                primary_key="id",
                tenant_field="tenant_id",
                fields=(
                    FieldDefinition("id", "integer"),
                    FieldDefinition("tenant_id", "string"),
                    FieldDefinition("delete_flag", "string"),
                    FieldDefinition("title", "string"),
                ),
                read_roles=frozenset({"management", "runtime"}),
                write_roles=frozenset({"management"}),
                active_field="delete_flag",
            ),
        )
    )


def scope(role="management", tenant="t1"):
    return StorageScope(role, tenant, "actor", frozenset({"documents"}))


def test_catalog_binds_tenant_active_policy_and_stable_sort(catalog):
    query = catalog.query("documents", scope(), RecordQuery(fields=("title",)))
    assert query.where.terms == (
        Comparison("tenant_id", "eq", "t1"),
        Comparison("delete_flag", "eq", "N"),
    )
    assert query.order_by == (Sort("id"),)


def test_conflicting_tenant_predicate_cannot_replace_bound_scope(catalog):
    query = catalog.query(
        "documents", scope(), RecordQuery(where=Comparison("tenant_id", "eq", "t2"))
    )
    assert Comparison("tenant_id", "eq", "t1") in query.where.terms
    assert Comparison("tenant_id", "eq", "t2") in query.where.terms


@pytest.mark.parametrize(
    "query",
    [
        RecordQuery(fields=("password",)),
        RecordQuery(where=Comparison("title", "script", "anything")),
        RecordQuery(where=Comparison("id", "eq", "wrong-type")),
        RecordQuery(order_by=(Sort("unknown"),)),
    ],
)
def test_unknown_fields_operators_and_types_are_rejected(catalog, query):
    with pytest.raises(InvalidInput):
        catalog.query("documents", scope(), query)


def test_runtime_has_no_write_authority(catalog):
    with pytest.raises(ScopeDenied):
        catalog.authorize("documents", scope("runtime"), write=True)


def test_explicit_system_scope_requires_catalog_permission(catalog):
    system = StorageScope(
        "management", None, "actor", frozenset({"documents"}), system=True
    )
    with pytest.raises(ScopeDenied):
        catalog.query("documents", system, RecordQuery())


def test_duplicate_catalog_names_are_rejected(catalog):
    definition = catalog.authorize("documents", scope())
    with pytest.raises(InvalidInput):
        DatasetCatalog((definition, definition))


def test_catalog_projects_only_declared_fields(catalog):
    query = catalog.query("documents", scope(), RecordQuery())
    assert query.fields == ("id", "tenant_id", "delete_flag", "title")


def test_required_resource_restrictions_are_not_silently_dropped(catalog):
    restricted = StorageScope(
        "management", "tenant", "actor", {"documents"}, resource_prefix="owned/"
    )
    with pytest.raises(CapabilityUnsupported):
        catalog.query("documents", restricted, RecordQuery())


def test_overly_complex_predicates_are_rejected(catalog):
    predicate = Comparison("id", "eq", 1)
    for _ in range(10):
        predicate = Junction("and", (predicate,))
    with pytest.raises(InvalidInput):
        catalog.query("documents", scope(), RecordQuery(where=predicate))
