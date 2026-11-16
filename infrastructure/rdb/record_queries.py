# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded record queries and transaction-local PostgreSQL claims."""

import base64
import hashlib
import json
import math
from dataclasses import asdict

import sqlalchemy as sa
from nexent.storage.errors import CapabilityUnsupported, Conflict, InvalidInput
from nexent.storage.models import Page, PageRequest, RecordQuery, Revision


def _normalized(store, dataset, query):
    if not isinstance(query, RecordQuery):
        raise InvalidInput()
    definition, table = store._definition(dataset)
    return definition, table, store._catalog.query(dataset, store.scope, query)


def _fingerprint(store, dataset, query, limit):
    value = {
        "dataset": dataset,
        "query": asdict(query),
        "scope": {
            "service": store.scope.service_role,
            "tenant": store.scope.tenant_id,
            "actor": store.scope.actor_id,
            "system": store.scope.system,
        },
        "limit": limit,
    }
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError):
        raise InvalidInput() from None
    return hashlib.sha256(raw).hexdigest()


def query_records(store, dataset, query, page, *, context):
    from infrastructure.rdb.record_store import _predicate

    if not isinstance(page, PageRequest):
        raise InvalidInput()
    _, table, query = _normalized(store, dataset, query)
    fingerprint = _fingerprint(store, dataset, query, page.limit)
    offset = 0
    if page.cursor is not None:
        try:
            if not isinstance(page.cursor, str) or len(page.cursor) > 512:
                raise ValueError()
            cursor = json.loads(
                base64.b64decode(page.cursor, altchars=b"-_", validate=True)
            )
            offset = cursor["offset"]
            if (
                cursor["query"] != fingerprint
                or type(offset) is not int
                or not 0 <= offset <= 1000000
            ):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise InvalidInput() from None
    statement = sa.select(*(table.c[name] for name in query.fields)).where(
        _predicate(table, query.where)
    )
    statement = (
        statement.order_by(
            *(
                table.c[item.field].desc()
                if item.descending
                else table.c[item.field].asc()
                for item in query.order_by
            )
        )
        .offset(offset)
        .limit(page.limit + 1)
    )
    with store._session(context) as connection:
        rows = store._execute(connection, statement, context).mappings().all()
        values = tuple(store._neutral(dataset, row) for row in rows[: page.limit])
        try:
            json.dumps(values, allow_nan=False)
        except (TypeError, ValueError):
            raise CapabilityUnsupported() from None
        next_cursor = None
        if len(rows) > page.limit:
            if offset + page.limit > 1000000:
                raise CapabilityUnsupported()
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {"offset": offset + page.limit, "query": fingerprint},
                    separators=(",", ":"),
                ).encode()
            ).decode()
        return Page(values, next_cursor)


def count_records(store, dataset, query, *, context):
    from infrastructure.rdb.record_store import _predicate

    _, table, query = _normalized(store, dataset, query)
    statement = (
        sa.select(sa.func.count())
        .select_from(table)
        .where(_predicate(table, query.where))
    )
    with store._session(context) as connection:
        return store._execute(connection, statement, context).scalar_one()


def claim_records(store, dataset, query, patch, *, limit, context):
    from infrastructure.rdb.record_store import _predicate

    store._check(context)
    if store._connection is None or store._engine.dialect.name != "postgresql":
        raise CapabilityUnsupported(operation_id=context.operation_id)
    page = PageRequest(limit=limit)
    definition, table = store._definition(dataset, write=True)
    store._patch_values(dataset, patch)
    _, _, query = _normalized(store, dataset, query)
    revision = store._revisions[dataset]
    statement = (
        sa.select(table.c[definition.primary_key], table.c[revision])
        .where(_predicate(table, query.where))
        .order_by(
            *(
                table.c[item.field].desc()
                if item.descending
                else table.c[item.field].asc()
                for item in query.order_by
            )
        )
        .limit(page.limit)
        .with_for_update(skip_locked=True)
    )
    rows = store._execute(store._connection, statement, context).all()
    result = []
    for key, version in rows:
        receipt = store.patch(
            dataset, key, patch, expected=Revision(str(version)), context=context
        )
        if not receipt.matched:
            raise Conflict(operation_id=context.operation_id)
        result.append(store.get(dataset, key, fields=query.fields, context=context))
    return tuple(result)


def sum_records(store, dataset, field, query, *, context):
    from infrastructure.rdb.record_store import _predicate

    definition, table, query = _normalized(store, dataset, query)
    numeric = {
        item.name: item.kind
        for item in definition.fields
        if item.kind in {"integer", "number"}
    }
    if not isinstance(field, str) or field not in numeric:
        raise InvalidInput()
    statement = sa.select(sa.func.sum(table.c[field])).where(
        _predicate(table, query.where)
    )
    with store._session(context) as connection:
        result = store._execute(connection, statement, context).scalar_one()
        return _numeric_total(result, numeric[field])


def _numeric_total(value, kind):
    if value is None:
        return 0
    if kind == "integer":
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        raise CapabilityUnsupported()
    return result


def sum_grouped_records(store, dataset, field, group_by, query, *, context):
    from infrastructure.rdb.record_store import _predicate

    definition, table, query = _normalized(store, dataset, query)
    kinds = {item.name: item.kind for item in definition.fields}
    if (
        not isinstance(field, str)
        or not isinstance(group_by, str)
        or kinds.get(field) not in {"integer", "number"}
        or kinds.get(group_by) not in {"string", "integer"}
    ):
        raise InvalidInput()
    statement = (
        sa.select(table.c[group_by], sa.func.sum(table.c[field]))
        .where(_predicate(table, query.where))
        .group_by(table.c[group_by])
    )
    with store._session(context) as connection:
        rows = store._execute(connection, statement, context).all()
        result = {}
        for key, value in rows:
            if type(key) not in {str, int}:
                raise CapabilityUnsupported()
            result[key] = _numeric_total(value, kinds[field])
        return result
