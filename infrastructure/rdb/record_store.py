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
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


def _predicate(table, value):
    if isinstance(value, Junction):
        operation = sa.and_ if value.operator == "and" else sa.or_
        return operation(*(_predicate(table, term) for term in value.terms))
    column = table.c[value.field]
    storage_type = column.type.impl if isinstance(column.type, sa.TypeDecorator) else column.type
    if (
        isinstance(storage_type, sa.DateTime)
        and value.value is not None
        and value.operator != "is_null"
    ):
        from dataclasses import replace

        from infrastructure.rdb.record_audit import timestamp

        value = replace(
            value,
            value=[
                timestamp(item, naive=not storage_type.timezone) for item in value.value
            ]
            if value.operator == "in"
            else timestamp(value.value, naive=not storage_type.timezone),
        )
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
    """Scoped record operations with explicit per-backend capabilities."""

    capabilities = CapabilitySet(
        frozenset(
            {
                "record.get",
                "record.create",
                "record.patch",
                "record.delete",
                "record.cas",
                "record.transaction",
                "record.query",
                "record.count",
                "record.sum",
                "record.sum_by",
            }
        )
    )

    def __init__(
        self, scope, catalog, tables, engine, *, revision_fields, audit_mappings=None, write_tables=None,
        transaction_locks=(),
    ):
        if (not isinstance(transaction_locks, tuple) or len(transaction_locks) > 16
            or any(not isinstance(key, str) or not key.strip() or len(key) > 512 for key in transaction_locks)
            or len(set(transaction_locks)) != len(transaction_locks)):
            raise InvalidInput()
        if transaction_locks and engine.dialect.name != 'postgresql':
            raise CapabilityUnsupported()
        self._transaction_locks = transaction_locks
        self._audits = MappingProxyType(dict(audit_mappings or {}))
        self._scope = scope
        self._catalog = catalog
        self._tables = MappingProxyType(dict(tables))
        self._write_tables = MappingProxyType(dict(write_tables or {}))
        if not self._write_tables.keys() <= self._tables.keys():
            raise InvalidInput()
        self._engine = engine
        self._revisions = MappingProxyType(dict(revision_fields))
        if not any(value is not None for value in self._revisions.values()):
            self.capabilities = CapabilitySet(self.capabilities.supported - {'record.cas'})
        self._connection = None
        self._thread = None
        self._closed = False
        self._deadline = None
        if engine.dialect.name == "postgresql":
            self.capabilities = CapabilitySet(
                self.capabilities.supported | {"record.claim.skip_locked"}
            )
        if engine.dialect.name not in {"postgresql", "sqlite"}:
            raise CapabilityUnsupported()
        if engine.get_execution_options().get("isolation_level") == "AUTOCOMMIT":
            raise CapabilityUnsupported()
        for name, table in self._tables.items():
            definition = catalog.authorize(name, scope)
            keys = (
                table.primary_key.columns
                if hasattr(table.primary_key, "columns")
                else table.primary_key
            )
            keys = tuple(column.name for column in keys)
            if not keys or keys[0] != definition.primary_key:
                raise CapabilityUnsupported()
            target = self._write_tables.get(name, table)
            if definition.write_roles and not isinstance(target, sa.Table):
                raise CapabilityUnsupported()
            if name in self._write_tables and tuple(c.name for c in target.primary_key.columns) != keys:
                raise CapabilityUnsupported()
            fields = {field.name for field in definition.fields}
            revision = self._revisions.get(name)
            if not fields <= set(table.c.keys()) or not set(keys) <= fields:
                raise InvalidInput()
            if revision is None:
                if definition.write_roles and (name not in self._revisions or name not in self._audits):
                    raise InvalidInput()
            elif revision not in fields:
                raise InvalidInput()
            elif not isinstance(table.c[revision].type, sa.Integer):
                raise CapabilityUnsupported()
            supported = {
                "string": sa.String,
                "integer": sa.Integer,
                "number": (sa.Float, sa.Integer),
                "boolean": sa.Boolean,
                "object": sa.JSON,
                "array": (sa.JSON, sa.ARRAY),
            }
            audit = self._audits.get(name)
            if audit is not None and (
                len(audit.fields) != 4
                or not (audit.fields | audit.extra_dates) <= fields
            ):
                raise InvalidInput()
            if audit is not None:
                if audit.fields & {
                    definition.primary_key,
                    definition.tenant_field,
                    definition.active_field,
                    revision,
                }:
                    raise InvalidInput()
                if definition.active_field:
                    if audit.inactive_value == definition.active_value:
                        raise InvalidInput()
                    catalog.query(
                        name,
                        scope,
                        RecordQuery(
                            where=Comparison(
                                definition.active_field, "eq", audit.inactive_value
                            )
                        ),
                    )
            for field in definition.fields:
                column_type = table.c[field.name].type
                storage_type = column_type.impl if isinstance(column_type, sa.TypeDecorator) else column_type
                if (
                    audit is not None
                    and field.name in audit.fields - audit.dates
                    and field.kind != "string"
                ):
                    raise CapabilityUnsupported()
                if audit is not None and field.name in audit.dates:
                    if field.kind != "string" or not isinstance(
                        storage_type, sa.DateTime
                    ):
                        raise CapabilityUnsupported()
                    continue
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
        except (DBAPIError, PoolTimeoutError):
            raise Unavailable(operation_id=context.operation_id) from None
        bound = SQLRecordStore(
            self.scope,
            self._catalog,
            self._tables,
            self._engine,
            revision_fields=self._revisions,
            audit_mappings=self._audits,
            write_tables=self._write_tables,
            transaction_locks=self._transaction_locks,
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
            for key in self._transaction_locks:
                bound._execute(connection, sa.text(
                    'SELECT pg_advisory_xact_lock(hashtext(:lock_key))'
                ).bindparams(lock_key=key), context)
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
        except DBAPIError as error:
            if getattr(error.orig, "pgcode", None) == "57014":
                raise DeadlineExceeded(operation_id=context.operation_id) from None
            if getattr(error.orig, "pgcode", None) in {"40001", "40P01"}:
                raise Conflict(operation_id=context.operation_id) from None
            raise Unavailable(operation_id=context.operation_id) from None

    def _definition(self, name, *, write=False):
        definition = self._catalog.authorize(name, self.scope, write=write)
        if name not in self._tables:
            raise ScopeDenied()
        return definition, self._write_tables.get(name, self._tables[name]) if write else self._tables[name]

    def _where(self, name, key, *, write=False):
        _, table = self._definition(name)
        keys = tuple(c.name for c in table.primary_key)
        values = key if isinstance(key, tuple) else (key,)
        if len(values) != len(keys) or any(type(value) not in (str, int) for value in values):
            raise InvalidInput()
        query = self._catalog.query(
            name,
            self.scope,
            RecordQuery(where=Junction('and', tuple(Comparison(field, 'eq', value) for field, value in zip(keys, values)))),
        )
        predicate = _predicate(table, query.where)
        if write and name in self._write_tables:
            target = self._write_tables[name]
            target_key = target.c[keys[0]] if len(keys) == 1 else sa.tuple_(*(target.c[field] for field in keys))
            return target_key.in_(sa.select(*(table.c[field] for field in keys)).where(predicate))
        return predicate

    def _write_revision(self, dataset, expected, context):
        revision = self._revisions.get(dataset)
        if revision is None and (self._connection is None or expected is not None):
            raise CapabilityUnsupported(operation_id=context.operation_id)
        return revision

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
        data = dict(values)
        audit = self._audits.get(name)
        if audit is not None:
            from infrastructure.rdb.record_audit import timestamp

            for field in audit.extra_dates & data.keys():
                if data[field] is not None:
                    data[field] = timestamp(
                        data[field], naive=not self._tables[name].c[field].type.timezone
                    )
        return data

    def _audit_values(self, dataset, *, create=False):
        from infrastructure.rdb.record_audit import timestamp

        values = self._audits[dataset].values(self.scope.actor_id, create=create)
        for field in self._audits[dataset].fields & values.keys():
            column = self._tables[dataset].c[field]
            if isinstance(column.type, sa.DateTime) and not column.type.timezone:
                values[field] = timestamp(values[field], naive=True)
        return values

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
            result = self._neutral(dataset, row)
            try:
                json.dumps(result, allow_nan=False)
            except (TypeError, ValueError):
                raise CapabilityUnsupported() from None
            return result

    def create(self, dataset, values, *, context):
        if dataset in self._write_tables:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        definition, table = self._definition(dataset, write=True)
        revision = self._write_revision(dataset, None, context)
        audit = self._audits.get(dataset)
        if audit is not None and audit.fields & values.keys():
            raise ScopeDenied()
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
        if revision in data:
            raise InvalidInput()
        if revision is not None:
            data[revision] = 1
        if audit is not None:
            data.update(self._audit_values(dataset, create=True))
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
            return self._neutral(dataset, row)

    def _patch_values(self, dataset, patch):
        definition, table = self._definition(dataset, write=True)
        if not isinstance(patch, FieldPatch):
            raise InvalidInput()
        names = set(patch.set_values) | set(patch.unset_fields) | set(patch.increments)
        protected = {
            definition.primary_key,
            definition.tenant_field,
            definition.active_field,
            self._revisions.get(dataset),
        }
        protected.update(c.name for c in table.primary_key)
        audit = self._audits.get(dataset)
        if audit is not None:
            protected.update(audit.fields)
        if names & protected:
            raise ScopeDenied()
        if not names <= set(table.c.keys()):
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
        if audit is not None:
            data.update(self._audit_values(dataset))
        return definition, table, data

    def patch(self, dataset, key, patch: FieldPatch, *, expected=None, context):
        _, table, data = self._patch_values(dataset, patch)
        revision = self._write_revision(dataset, expected, context)
        if revision is not None:
            data[revision] = table.c[revision] + 1
        where = self._where(dataset, key, write=True)
        if expected is not None:
            if not isinstance(expected, Revision) or not expected.value.isdecimal():
                raise InvalidInput()
            where = sa.and_(where, table.c[revision] == int(expected.value))
        with self._session(context) as connection:
            row = self._execute(
                connection,
                table.update().where(where).values(**data).returning(
                    table.c[revision] if revision is not None else sa.literal(1)),
                context,
            ).first()
            return WriteReceipt(
                context.operation_id,
                row is not None,
                Revision(str(row[0])) if row and revision is not None else None,
            )

    def delete(self, dataset, key, *, expected=None, context):
        definition, table = self._definition(dataset, write=True)
        revision = self._write_revision(dataset, expected, context)
        if definition.active_field and dataset not in self._audits:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        where = self._where(dataset, key, write=True)
        if expected is not None:
            if not isinstance(expected, Revision) or not expected.value.isdecimal():
                raise InvalidInput()
            where = sa.and_(
                where, table.c[self._revisions[dataset]] == int(expected.value)
            )
        with self._session(context) as connection:
            statement = table.delete().where(where)
            if definition.active_field:
                audit = self._audits[dataset]
                values = self._audit_values(dataset)
                values[definition.active_field] = audit.inactive_value
                if revision is not None:
                    values[revision] = table.c[revision] + 1
                statement = table.update().where(where).values(**values)
            result = self._execute(connection, statement, context)
            return DeleteReceipt(context.operation_id, bool(result.rowcount))

    def _neutral(self, dataset, row):
        audit = self._audits.get(dataset)
        return audit.neutral(row) if audit is not None else dict(row)

    def query(self, dataset, query, page, *, context):
        from infrastructure.rdb.record_queries import query_records

        return query_records(self, dataset, query, page, context=context)

    def count(self, dataset, query, *, context):
        from infrastructure.rdb.record_queries import count_records

        return count_records(self, dataset, query, context=context)

    def sum(self, dataset, field, query, *, context):
        from infrastructure.rdb.record_queries import sum_records

        return sum_records(self, dataset, field, query, context=context)

    def sum_by(self, dataset, field, group_by, query, *, context):
        from infrastructure.rdb.record_queries import sum_grouped_records

        return sum_grouped_records(
            self, dataset, field, group_by, query, context=context
        )

    def claim(self, dataset, query, patch, *, limit=1, context):
        from infrastructure.rdb.record_queries import claim_records

        return claim_records(self, dataset, query, patch, limit=limit, context=context)

    def close(self):
        self._closed = True
