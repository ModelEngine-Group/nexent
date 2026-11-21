# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


"""Pydantic request models for ontology routes."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ext_components.aidp.apps.aidp_ontology_validation import (
    _ENTITY_DESCRIPTION_MAX_CHARS,
    _ENTITY_NAME_MAX_CHARS,
    _clean_required,
    _validate_domain_description,
    _validate_domain_name,
    _validate_field_name,
)
from ext_components.aidp.services.aidp_ontology_common import CHUNK_BATCH_MAX_IDS


class EntityPropertyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_name: str = Field(..., min_length=1)
    display_name: str | None = None
    data_type: str = Field(
        "string",
        description="AIDP property data_type (str/string/float/datetime/list[str])",
    )
    range: str | None = Field(None, description="AIDP property range; any string")
    value: str | None = Field(
        "", description="Property value; empty string is the only legal blank"
    )


class OntologyDomainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Ontology domain name (<= 64 UTF-8 bytes)")
    description: str = Field(
        "", description="Ontology domain description (<= 512 UTF-8 bytes)"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_domain_name(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _validate_domain_description(value)


class OntologyDomainUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, description="New ontology domain name")
    description: str | None = Field(None, description="New ontology domain description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _validate_domain_name(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return _validate_domain_description(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.description is None:
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class OntologyEntityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["type", "entity"]
    api_name: str = Field(..., description="Stable AIDP entity API name")
    display_name: str | None = None
    description: str | None = None
    properties: list[EntityPropertyRequest] = Field(default_factory=list)
    primary_properties: list[str] = Field(default_factory=list)
    type_id: str | None = None
    parent_entities: list[str] = Field(default_factory=list)
    synonym_entities: list[str] = Field(default_factory=list)
    child_entities: list[str] = Field(default_factory=list)

    @field_validator("api_name")
    @classmethod
    def validate_api_name(cls, value: str) -> str:
        api_name = _clean_required(value, "英文标识不能为空")
        if len(api_name) > _ENTITY_NAME_MAX_CHARS:
            raise ValueError(f"英文标识不能超过 {_ENTITY_NAME_MAX_CHARS} 个字符")
        # Confirmed AIDP rule: letter first, then letters/digits/underscores,
        # and the name must not end with an underscore.
        if not re.match(r"^[A-Za-z](?:[A-Za-z0-9_]*[A-Za-z0-9])?$", api_name):
            raise ValueError(
                "英文标识需字母开头，只能包含字母、数字、下划线，且不能以下划线结尾"
            )
        return api_name

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        description = value.strip()
        if len(description) > _ENTITY_DESCRIPTION_MAX_CHARS:
            raise ValueError(f"实体描述不能超过 {_ENTITY_DESCRIPTION_MAX_CHARS} 个字符")
        return description

    @model_validator(mode="after")
    def validate_kind_rules(self):
        if self.kind == "type" and self.type_id:
            raise ValueError("Type 不能选择所属实体类型")
        if self.kind == "type" and self.parent_entities:
            raise ValueError("类型不能设置上位实体")
        property_names = [item.api_name.strip() for item in self.properties]
        if len(set(property_names)) != len(property_names):
            raise ValueError("属性 api_name 不能重复")
        missing = [
            name for name in self.primary_properties if name not in property_names
        ]
        if missing:
            raise ValueError("主属性必须来自已配置的属性")
        return self


class OntologyEntityUpdateRequest(BaseModel):
    """Fields accepted for an existing entity.

    ``parent_entities``/``child_entities`` are not part of AIDP's entity PATCH;
    they are translated into Relations create/delete calls by the handler.
    ``synonym_entities`` is likewise applied through the ``synonym`` property.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    properties: list[EntityPropertyRequest] | None = None
    primary_properties: list[str] | None = None
    parent_entities: list[str] | None = None
    child_entities: list[str] | None = None
    synonym_entities: list[str] | None = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        description = value.strip()
        if len(description) > _ENTITY_DESCRIPTION_MAX_CHARS:
            raise ValueError(f"实体描述不能超过 {_ENTITY_DESCRIPTION_MAX_CHARS} 个字符")
        return description

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class OntologyBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str | None = Field(
        default=None, min_length=1, description="Target AIDP knowledge base ID"
    )
    kds_id: str | None = Field(
        default=None, min_length=1, description="Legacy spelling for kb_id"
    )

    @model_validator(mode="after")
    def require_kb_id(self):
        if not (self.kb_id or self.kds_id):
            raise ValueError("kb_id is required")
        return self

    @property
    def target_kb_id(self) -> str:
        return (self.kb_id or self.kds_id or "").strip()


class OntologyMetadataFieldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(
        ..., description="Field name, at most 63 characters and 64 UTF-8 bytes"
    )
    field_type: Literal["string", "number", "date"]

    @field_validator("field_name")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        return _validate_field_name(value)


class OntologyRulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    enabled: bool = True
    condition: dict[str, Any]
    action: dict[str, Any]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("规则名称不能为空")
        return stripped


class OntologyRelationRequest(BaseModel):
    """Confirmed relation contract: only `is` and `is-a` exist."""

    model_config = ConfigDict(extra="forbid")

    api_name: Literal["is", "is-a"]
    display_name: str = Field(..., min_length=1, max_length=64)
    source_kind: Literal["type", "entity"]
    source_id: str = Field(..., min_length=1, max_length=20)
    object_kind: Literal["type", "entity"]
    object_id: str = Field(..., min_length=1, max_length=20)

    @field_validator("source_id", "object_id")
    @classmethod
    def validate_numeric_id(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("关系端点 ID 必须是数字")
        return value


class OntologyMetadataUnbindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata_ids: list[str] = Field(..., min_length=1)


class OntologyMetadataFieldRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_field_name: str = Field(
        ..., description="New field name, at most 63 characters and 64 UTF-8 bytes"
    )

    @field_validator("new_field_name")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        return _validate_field_name(value)


class ChunkMetadataUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str = Field(
        ..., min_length=1, description="Ontology domain that owns the fields"
    )
    metadata: dict[str, Any] = Field(..., min_length=1)
    chunk_ids: list[int | str] = Field(..., min_length=1)

    @field_validator("chunk_ids")
    @classmethod
    def validate_chunk_ids(cls, value: list[int | str]) -> list[int | str]:
        if len(value) > CHUNK_BATCH_MAX_IDS:
            raise ValueError(f"单次最多标注 {CHUNK_BATCH_MAX_IDS} 个 Chunk")
        return value


class OntologyExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_properties: bool = True
    include_relations: bool = True
    kind: Literal["all", "type", "entity"] | None = None


class OntologyImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field("ontology.json", min_length=1, max_length=255)
    document: dict[str, Any] = Field(..., description="Parsed AIDP export JSON")
