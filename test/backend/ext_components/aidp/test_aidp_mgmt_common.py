# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Coverage for AIDP management request-boundary helpers."""

from __future__ import annotations

import importlib

import pytest
from pydantic import BaseModel, ValidationError


def _common():
    return importlib.import_module("ext_components.aidp.apps.aidp_mgmt_common")


def test_folder_path_validation():
    common = _common()
    assert common._validate_folder_path("/a/b") == "/a/b"
    assert common._validate_folder_path("/") == "/"
    for value in ("a", "/a//b", "/a/../b"):
        # Backslash is generated at runtime so the source has no escape ambiguity.
        with pytest.raises(ValueError):
            common._validate_folder_path("/a" + chr(92) + "b")
        with pytest.raises(ValueError):
            common._validate_folder_path(value)
    with pytest.raises(ValueError):
        common._validate_folder_path("/", allow_root=False)


def test_folder_name_and_relative_path():
    common = _common()
    assert common._validate_folder_name(" name ") == " name "
    with pytest.raises(ValueError):
        common._validate_folder_name("..")
    assert common._relative_path_to_directory("a/b") == "a"
    assert common._relative_path_to_directory("a") == ""
    with pytest.raises(ValueError):
        common._relative_path_to_directory("../a")
    with pytest.raises(ValueError):
        common._validate_non_root_folder_path("/")


def test_folder_path_model():
    common = _common()

    class Model(BaseModel):
        path: common.FolderPath
        name: common.FolderName

    model = Model(path="/a", name=" n ")
    assert model.name == "n"
    with pytest.raises(ValidationError):
        Model(path="bad", name="n")


def _request(headers):
    from starlette.requests import Request

    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


@pytest.mark.asyncio
async def test_auth_header_and_tenant_errors(monkeypatch):
    import asyncio

    common = _common()

    with pytest.raises(Exception):
        await common._auth(_request({}))

    def bad_token(_auth):
        raise common.UnauthorizedError("bad")

    monkeypatch.setattr(common.auth_utils_module, "get_current_user_id", bad_token)
    with pytest.raises(Exception):
        await common._auth(_request({"Authorization": "Bearer x"}))

    monkeypatch.setattr(
        common.auth_utils_module, "get_current_user_id", lambda _auth: ("u", "")
    )
    with pytest.raises(Exception):
        await common._auth(_request({"Authorization": "Bearer x"}))

    monkeypatch.setattr(
        common.auth_utils_module, "get_current_user_id", lambda _auth: ("u", "t")
    )
    assert await common._auth(
        _request({"Authorization": "Bearer x", "Accept-Language": "en-US"})
    ) == ("u", "t")
