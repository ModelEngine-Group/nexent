# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Logical record schemas, field checks and mandatory scope predicates."""

from dataclasses import dataclass, replace
from types import MappingProxyType

from nexent.storage.errors import CapabilityUnsupported, InvalidInput, ScopeDenied
from nexent.storage.models import Comparison, Junction, RecordQuery, Sort, StorageScope

_FIELD_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}
_OPERATORS = frozenset({"eq", "ne", "in", "lt", "lte", "gt", "gte", "is_null"})


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    kind: str
    nullable: bool = False

    def __post_init__(self):
        if not self.name or self.kind not in _FIELD_TYPES:
            raise InvalidInput()


@dataclass(frozen=True)
class DatasetDefinition:
    name: str
    primary_key: str
    fields: tuple[FieldDefinition, ...]
    read_roles: frozenset[str]
    write_roles: frozenset[str] = frozenset()
    tenant_field: str | None = None
    active_field: str | None = None
    active_value: str = "N"
    allow_system: bool = False

    def __post_init__(self):
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "read_roles", frozenset(self.read_roles))
        object.__setattr__(self, "write_roles", frozenset(self.write_roles))
        names = {item.name for item in self.fields}
        if (
            not self.name
            or len(names) != len(self.fields)
            or self.primary_key not in names
        ):
            raise InvalidInput()
        if type(self.allow_system) is not bool:
            raise InvalidInput()
        if self.tenant_field is not None and self.tenant_field not in names:
            raise InvalidInput()
        if self.active_field is not None and self.active_field not in names:
            raise InvalidInput()


class DatasetCatalog:
    def __init__(self, definitions: tuple[DatasetDefinition, ...]):
        datasets = {item.name: item for item in definitions}
        if len(datasets) != len(definitions):
            raise InvalidInput()
        self._datasets = MappingProxyType(datasets)

    def authorize(
        self, name: str, scope: StorageScope, *, write: bool = False
    ) -> DatasetDefinition:
        if scope.resource_prefix:
            # Record-key range policies need explicit dataset-specific compilation.
            raise CapabilityUnsupported()
        dataset = self._datasets.get(name)
        if dataset is None or name not in scope.namespaces:
            raise ScopeDenied()
        roles = dataset.write_roles if write else dataset.read_roles
        if scope.service_role not in roles:
            raise ScopeDenied()
        if scope.system:
            if not dataset.allow_system:
                raise ScopeDenied()
        elif dataset.tenant_field is None:
            # Shared datasets need an explicitly granted system handle.
            raise ScopeDenied()
        return dataset

    def query(self, name: str, scope: StorageScope, query: RecordQuery) -> RecordQuery:
        dataset = self.authorize(name, scope)
        fields = {item.name: item for item in dataset.fields}
        if not isinstance(query, RecordQuery):
            raise InvalidInput()
        if any(name not in fields for name in query.fields):
            raise InvalidInput()
        if any(
            not isinstance(item, Sort)
            or item.field not in fields
            or type(item.descending) is not bool
            for item in query.order_by
        ):
            raise InvalidInput()
        terms = []
        if query.where is not None:
            self._validate_predicate(query.where, fields)
            terms.append(query.where)
        if not scope.system:
            terms.append(Comparison(dataset.tenant_field, "eq", scope.tenant_id))
        if dataset.active_field is not None:
            terms.append(Comparison(dataset.active_field, "eq", dataset.active_value))
        order = query.order_by
        if not any(item.field == dataset.primary_key for item in order):
            order += (Sort(dataset.primary_key),)
        return replace(
            query,
            fields=query.fields or tuple(fields),
            where=Junction("and", tuple(terms)),
            order_by=order,
        )

    def _validate_predicate(self, predicate, fields, depth=0, budget=None):
        if budget is None:
            budget = [64]
        budget[0] -= 1
        if depth > 8 or budget[0] < 0:
            raise InvalidInput()
        if isinstance(predicate, Junction):
            if predicate.operator not in {"and", "or"} or not predicate.terms:
                raise InvalidInput()
            for term in predicate.terms:
                self._validate_predicate(term, fields, depth + 1, budget)
            return
        if not isinstance(predicate, Comparison) or predicate.field not in fields:
            raise InvalidInput()
        definition = fields[predicate.field]
        if predicate.operator not in _OPERATORS:
            raise InvalidInput()
        if predicate.operator == "is_null":
            if type(predicate.value) is not bool:
                raise InvalidInput()
            return
        values = [predicate.value]
        if predicate.operator == "in":
            if (
                not isinstance(predicate.value, list)
                or not 1 <= len(predicate.value) <= 1000
            ):
                raise InvalidInput()
            values = predicate.value
        if definition.kind in {"object", "array"} and predicate.operator not in {
            "eq",
            "ne",
        }:
            raise InvalidInput()
        for value in values:
            if value is None:
                if not definition.nullable or predicate.operator not in {"eq", "ne"}:
                    raise InvalidInput()
            elif (
                not isinstance(value, _FIELD_TYPES[definition.kind])
                or isinstance(value, bool)
                and definition.kind in {"integer", "number"}
            ):
                raise InvalidInput()
