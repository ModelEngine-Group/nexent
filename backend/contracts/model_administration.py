# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AgentOS input models for the existing model administration operations."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, JsonValue, AfterValidator

from contracts.model import BatchCreateModelsRequest, ModelProbeRequest, ModelRequest, ProviderModelRequest

_WRITE_FIELDS = (ModelRequest.model_fields.keys() | {"model_repo", "ssl_verify"}) - {
    "accepted_suggestion_match_kind", "accepted_capability_profile_version", "skip_default_backfill",
}


def _check_patch(patch: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if patch.keys() - (_WRITE_FIELDS | {"model_id"}):
        raise ValueError("Unsupported model fields")
    return patch


ModelPatch = Annotated[dict[str, JsonValue], AfterValidator(_check_patch)]


class ModelRegistration(ModelRequest):
    model_config = ConfigDict(extra="forbid")
    model_repo: str | None = None
    ssl_verify: bool | None = None

    def definition(self) -> dict:
        return self.model_dump(include=_WRITE_FIELDS, exclude_unset=True)


class ModelTenantDeactivation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str


class ModelUpdate(ModelSelection):
    patch: ModelPatch


class ModelHealthcheck(ModelSelection):
    model_type: str | None = None


class ModelBatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patches: list[ModelPatch]


class ModelProviderImport(BatchCreateModelsRequest):
    model_config = ConfigDict(extra="forbid")


class ModelProviderDiscovery(ProviderModelRequest):
    model_config = ConfigDict(extra="forbid")


class ModelProviderList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model_type: str | None = None


class ModelProbe(ModelProbeRequest):
    model_config = ConfigDict(extra="forbid")
