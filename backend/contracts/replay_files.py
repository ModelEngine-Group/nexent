# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Versioned file state for development replay, separate from the Agent's input."""
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from nexent.core.agents.resources.replay_files import file_name, validate_files


FileName = Annotated[str, AfterValidator(file_name)]
TextFiles = Annotated[dict[str, str], AfterValidator(validate_files)]


class FileStateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    adapter: Literal["text-files-v1"] = "text-files-v1"
    initial: TextFiles
    expected: TextFiles
    protected: list[FileName] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def consistent_protection(self):
        names = self.initial.keys() | self.expected.keys() | set(self.protected)
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError("Use consistent capitalization for each filename")
        if len(set(self.protected)) != len(self.protected):
            raise ValueError("Choose each protected file once")
        if any(self.initial.get(n) != self.expected.get(n) for n in self.protected):
            raise ValueError("A protected file must have the same initial and expected content")
        return self


class FileStateReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    initial_digest: str = Field(pattern="^[a-f0-9]{64}$")
    files: TextFiles
    bound: list[str] = Field(max_length=3)
    writes: list[FileName] = Field(max_length=32)
    writes_by_tool: dict[str, list[FileName]] = Field(default_factory=dict, max_length=32)
    complete: bool
