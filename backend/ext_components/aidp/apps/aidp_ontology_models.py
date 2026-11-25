# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


"""Pydantic request models for ontology routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ext_components.aidp.apps.aidp_ontology_validation import (
    DomainDescription,
    DomainName,
    EntityApiName,
    EntityDescription,
    EntityName,
    MetadataFieldName,
    NumericId,
    RuleDescription,
    RuleName,
)


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

    name: DomainName = Field(
        ..., description="Ontology domain name (<= 64 UTF-8 bytes)"
    )
    description: DomainDescription = Field(
        "", description="Ontology domain description (<= 512 UTF-8 bytes)"
    )


class OntologyDomainUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DomainName | None = Field(None, description="New ontology domain name")
    description: DomainDescription | None = Field(
        None, description="New ontology domain description"
    )

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.description is None:
            raise ValueError("at least one field must be provided")
        return self


class OntologyEntityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["type", "entity"]
    api_name: EntityApiName = Field(..., description="Stable AIDP entity API name")
    display_name: EntityName | None = None
    description: EntityDescription | None = None
    properties: list[EntityPropertyRequest] = Field(default_factory=list)
    primary_properties: list[str] = Field(default_factory=list)
    type_id: str | None = None
    parent_entities: list[str] = Field(default_factory=list)
    synonym_entities: list[str] = Field(default_factory=list)
    child_entities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_kind_rules(self):
        if self.kind == "type" and self.type_id:
            raise ValueError("a type cannot have a type_id")
        if self.kind == "type" and self.parent_entities:
            raise ValueError("a type cannot have parent entities")
        property_names = [item.api_name.strip() for item in self.properties]
        if len(set(property_names)) != len(property_names):
            raise ValueError("property api_name values must be unique")
        missing = [
            name for name in self.primary_properties if name not in property_names
        ]
        if missing:
            raise ValueError("primary properties must be configured properties")
        return self


class OntologyEntityUpdateRequest(BaseModel):
    """Fields accepted for an existing entity.

    ``parent_entities``/``child_entities`` are not part of AIDP's entity PATCH;
    they are translated into Relations create/delete calls by the handler.
    ``synonym_entities`` is likewise applied through the ``synonym`` property.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: EntityName | None = None
    description: EntityDescription | None = None
    properties: list[EntityPropertyRequest] | None = None
    primary_properties: list[str] | None = None
    parent_entities: list[str] | None = None
    child_entities: list[str] | None = None
    synonym_entities: list[str] | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("at least one field must be provided")
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

    field_name: MetadataFieldName = Field(
        ..., description="Field name, at most 63 characters and 64 UTF-8 bytes"
    )
    field_type: Literal["string", "number", "date"]


class OntologyRulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RuleName
    description: RuleDescription = ""
    enabled: bool = True
    condition: dict[str, Any]
    action: dict[str, Any]


class OntologyRelationRequest(BaseModel):
    """Confirmed relation contract: only `is` and `is-a` exist."""

    model_config = ConfigDict(extra="forbid")

    api_name: Literal["is", "is-a"]
    display_name: EntityName
    source_kind: Literal["type", "entity"]
    source_id: NumericId
    object_kind: Literal["type", "entity"]
    object_id: NumericId


class OntologyMetadataUnbindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata_ids: list[str] = Field(..., min_length=1)


class OntologyMetadataFieldRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_field_name: MetadataFieldName = Field(
        ..., description="New field name, at most 63 characters and 64 UTF-8 bytes"
    )


class OntologyExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_properties: bool = True
    include_relations: bool = True
    kind: Literal["all", "type", "entity"] | None = None


class OntologyImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field("ontology.json", min_length=1, max_length=255)
    document: dict[str, Any] = Field(..., description="Parsed AIDP export JSON")
