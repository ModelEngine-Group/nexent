# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped SQLAlchemy record operations without leaking connections or expressions."""

import asyncio
import json
from contextlib import contextmanager
from threading import get_ident
from time import monotonic
from types import MappingProxyType

import sqlalchemy as sa
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    CapabilitySet,
    Comparison,
    DeleteReceipt,
    FieldPatch,
    Junction,
    ReadConsistency,
    RecordQuery,
    Revision,
    WriteReceipt,
)
from sqlalchemy.exc import DBAPIError, IntegrityError


def _predicate(table, value):
    if isinstance(value, Junction):
        operation = sa.and_ if value.operator == "and" else sa.or_
        return operation(*(_predicate(table, term) for term in value.terms))
    column = table.c[value.field]
    operations = {
        "eq": lambda: column == value.value,
        "ne": lambda: column != value.value,
        "lt": lambda: column < value.value,
        "lte": lambda: column <= value.value,
        "gt": lambda: column > value.value,
        "gte": lambda: column >= value.value,
        "in": lambda: column.in_(value.value),
        "is_null": lambda: column.is_(None) if value.value else column.is_not(None),
    }
    return operations[value.operator]()


class SQLRecordStore:
    """Initial key-addressed subset; query/claim capabilities are deliberately absent."""

    capabilities = CapabilitySet(
        frozenset(
            {
                "record.get",
                "record.create",
                "record.patch",
                "record.delete",
                "record.cas",
                "record.transaction",
            }
        )
    )

    def __init__(self, scope, catalog, tables, engine, *, revision_fields):
        self._scope = scope
        self._catalog = catalog
        self._tables = MappingProxyType(dict(tables))
        self._engine = engine
        self._revisions = MappingProxyType(dict(revision_fields))
        self._connection = None
        self._thread = None
        self._closed = False
        self._deadline = None
        if engine.dialect.name not in {"postgresql", "sqlite"}:
            raise CapabilityUnsupported()
        if engine.get_execution_options().get("isolation_level") == "AUTOCOMMIT":
            raise CapabilityUnsupported()
        for name, table in self._tables.items():
            definition = catalog.authorize(name, scope)
            if [column.name for column in table.primary_key.columns] != [
                definition.primary_key
            ]:
                raise CapabilityUnsupported()
            fields = {field.name for field in definition.fields}
            revision = self._revisions.get(name)
            if not fields <= set(table.c.keys()) or revision not in fields:
                raise InvalidInput()
            if not isinstance(table.c[revision].type, sa.Integer):
                raise CapabilityUnsupported()
            supported = {
                "string": sa.String,
                "integer": sa.Integer,
                "number": (sa.Float, sa.Integer),
                "boolean": sa.Boolean,
                "object": sa.JSON,
                "array": sa.JSON,
            }
            for field in definition.fields:
                if not isinstance(
                    table.c[field.name].type, supported[field.kind]
                ) or isinstance(table.c[field.name].type, sa.Enum):
                    raise CapabilityUnsupported()

    @property
    def scope(self):
        return self._scope

    def _check(self, context):
        if self._closed or self._thread is not None and self._thread != get_ident():
            raise ScopeDenied(operation_id=context.operation_id)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        remaining = context.remaining()
        if self._deadline is not None:
            remaining = min(remaining, self._deadline - monotonic())
            if remaining <= 0:
                raise DeadlineExceeded(operation_id=context.operation_id)
        return remaining

    @contextmanager
    def _session(self, context):
        self._check(context)
        if self._connection is not None:
            yield self._connection
        else:
            with self.transaction(context=context) as bound:
                yield bound._connection

    @contextmanager
    def transaction(self, *, context):
        self._check(context)
        if self._connection is not None:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        try:
            connection = self._engine.connect()
        except DBAPIError:
            raise Unavailable(operation_id=context.operation_id) from None
        bound = SQLRecordStore(
            self.scope,
            self._catalog,
            self._tables,
            self._engine,
            revision_fields=self._revisions,
        )
        bound._connection = connection
        bound._thread = get_ident()
        bound._deadline = context.deadline
        transaction = None
        failed = False
        try:
            if getattr(connection.connection.driver_connection, "autocommit", False):
                raise CapabilityUnsupported()
            try:
                transaction = connection.begin()
            except DBAPIError:
                raise Unavailable(operation_id=context.operation_id) from None
            yield bound
            context.remaining()
            try:
                transaction.commit()
            except DBAPIError:
                raise OutcomeUnknown(operation_id=context.operation_id) from None
        except BaseException:
            failed = True
            if transaction is not None and transaction.is_active:
                try:
                    transaction.rollback()
                except DBAPIError:
                    pass  # Keep the original failure, especially an unknown commit outcome.
            raise
        finally:
            bound._closed = True
            try:
                connection.close()
            except DBAPIError:
                if not failed:
                    raise Unavailable(operation_id=context.operation_id) from None

    def _execute(self, connection, statement, context):
        remaining = self._check(context)
        try:
            if connection.dialect.name == "postgresql":
                # SET LOCAL is confined to this transaction; no SQL comes from callers.
                connection.execute(
                    sa.text("SELECT set_config('statement_timeout', :ms, true)"),
                    {"ms": str(max(1, int(remaining * 1000)))},
                )
            return connection.execute(statement)
        except IntegrityError as error:
            duplicate = getattr(error.orig, "pgcode", None) == "23505" or getattr(
                error.orig, "sqlite_errorcode", None
            ) in {1555, 2067}
            failure = Conflict if duplicate else InvalidInput
            raise failure(operation_id=context.operation_id) from None
        except DBAPIError:
            raise Unavailable(operation_id=context.operation_id) from None

    def _definition(self, name, *, write=False):
        definition = self._catalog.authorize(name, self.scope, write=write)
        if name not in self._tables:
            raise ScopeDenied()
        return definition, self._tables[name]

    def _where(self, name, key):
        definition, table = self._definition(name)
        query = self._catalog.query(
            name,
            self.scope,
            RecordQuery(where=Comparison(definition.primary_key, "eq", key)),
        )
        return _predicate(table, query.where)

    def _values(self, name, values):
        # Catalog validation reuses the same typed field checks as query literals.
        for field, value in values.items():
            self._catalog.query(
                name, self.scope, RecordQuery(where=Comparison(field, "eq", value))
            )
        try:
            json.dumps(values, allow_nan=False)
        except (ValueError, TypeError):
            raise InvalidInput() from None
        return dict(values)

    def get(
        self,
        dataset,
        key,
        *,
        fields=(),
        consistency=ReadConsistency.AUTHORITATIVE,
        context,
    ):
        if not isinstance(consistency, ReadConsistency):
            raise InvalidInput()
        _, table = self._definition(dataset)
        query = self._catalog.query(dataset, self.scope, RecordQuery(fields=fields))
        statement = sa.select(*(table.c[field] for field in query.fields)).where(
            self._where(dataset, key)
        )
        with self._session(context) as connection:
            row = self._execute(connection, statement, context).mappings().first()
            if row is None:
                return None
            result = dict(row)
            try:
                json.dumps(result, allow_nan=False)
            except (TypeError, ValueError):
                raise CapabilityUnsupported() from None
            return result

    def create(self, dataset, values, *, context):
        definition, table = self._definition(dataset, write=True)
        data = self._values(dataset, values)
        if not self.scope.system:
            if (
                definition.tenant_field in data
                and data[definition.tenant_field] != self.scope.tenant_id
            ):
                raise ScopeDenied()
            data[definition.tenant_field] = self.scope.tenant_id
        if definition.active_field:
            if (
                definition.active_field in data
                and data[definition.active_field] != definition.active_value
            ):
                raise ScopeDenied()
            data[definition.active_field] = definition.active_value
        revision = self._revisions[dataset]
        if revision in data:
            raise InvalidInput()
        data[revision] = 1
        with self._session(context) as connection:
            row = (
                self._execute(
                    connection,
                    table.insert()
                    .values(**data)
                    .returning(*(table.c[field.name] for field in definition.fields)),
                    context,
                )
                .mappings()
                .one()
            )
            return dict(row)

    def patch(self, dataset, key, patch: FieldPatch, *, expected=None, context):
        definition, table = self._definition(dataset, write=True)
        if not isinstance(patch, FieldPatch):
            raise InvalidInput()
        names = set(patch.set_values) | set(patch.unset_fields) | set(patch.increments)
        protected = {
            definition.primary_key,
            definition.tenant_field,
            definition.active_field,
            self._revisions[dataset],
        }
        if names & protected:
            raise ScopeDenied()
        if len(names) != len(patch.set_values) + len(patch.unset_fields) + len(
            patch.increments
        ):
            raise InvalidInput()
        data = self._values(
            dataset, {**patch.set_values, **dict.fromkeys(patch.unset_fields)}
        )
        for field, delta in patch.increments.items():
            self._values(dataset, {field: delta})
            if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                raise InvalidInput()
            data[field] = table.c[field] + delta
        revision = self._revisions[dataset]
        data[revision] = table.c[revision] + 1
        where = self._where(dataset, key)
        if expected is not None:
            if not isinstance(expected, Revision) or not expected.value.isdecimal():
                raise InvalidInput()
            where = sa.and_(where, table.c[revision] == int(expected.value))
        with self._session(context) as connection:
            row = self._execute(
                connection,
                table.update().where(where).values(**data).returning(table.c[revision]),
                context,
            ).first()
            return WriteReceipt(
                context.operation_id,
                row is not None,
                Revision(str(row[0])) if row else None,
            )

    def delete(self, dataset, key, *, expected=None, context):
        definition, table = self._definition(dataset, write=True)
        if definition.active_field:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        where = self._where(dataset, key)
        if expected is not None:
            if not isinstance(expected, Revision) or not expected.value.isdecimal():
                raise InvalidInput()
            where = sa.and_(
                where, table.c[self._revisions[dataset]] == int(expected.value)
            )
        with self._session(context) as connection:
            result = self._execute(connection, table.delete().where(where), context)
            return DeleteReceipt(context.operation_id, bool(result.rowcount))

    def query(self, dataset, query, page, *, context):
        raise CapabilityUnsupported(operation_id=context.operation_id)

    def count(self, dataset, query, *, context):
        raise CapabilityUnsupported(operation_id=context.operation_id)

    def close(self):
        self._closed = True
