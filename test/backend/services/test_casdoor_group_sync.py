# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json

import httpx
import pytest

from contracts.errors.exceptions import ValidationError
from management.services.permission.identity import casdoor_groups as sync


def group(name, parent="org"):
    return {"name": name, "createdTime": "2026-11-11T00:00:00Z", "parentId": parent, "isEnabled": True}


def test_group_directory_parses_direct_parents_regardless_of_input_order():
    result = sync._parse_groups([group("child", "root"), group("root")], "org")
    assert result["child"]["parent"] == "root"
    assert result["root"]["parent"] is None
    assert result["root"]["key"] == "root/2026-11-11T00:00:00Z"


@pytest.mark.parametrize("rows", [
    [group("one", "one")], [group("one", "other/parent")],
    [group("one", "two"), group("two", "one")],
])
def test_group_directory_rejects_invalid_parent_graph(rows):
    with pytest.raises(ValidationError):
        sync._parse_groups(rows, "org")


def test_bound_members_use_external_subject_and_ignore_ambiguous_matches(monkeypatch):
    one = {"id": "first", "name": "current-name"}
    two = {"id": "second", "name": "other-name"}
    bindings = [
        ("member", sync.subject_key("first")),
        ("ambiguous", sync.subject_key("first")),
        ("ambiguous", sync.subject_key("second")),
        ("missing", sync.subject_key("unavailable")),
    ]
    monkeypatch.setattr(sync, "tenant_bindings", lambda session, tenant_id: bindings)
    assert sync._bound_users(object(), "tenant", [one, two]) == {"member": one}


def test_incomplete_user_response_cannot_revoke_memberships():
    with pytest.raises(sync.CasdoorGroupUnavailable):
        sync._user_groups({})
    assert sync._user_groups({"groups": None}) == set()


def test_membership_write_changes_only_group_column_and_preserves_other_groups():
    current = {"owner": "org", "id": "stable", "name": "member", "password": "masked",
               "groups": ["org/existing"]}
    writes = []

    def respond(request):
        if request.method == "POST":
            assert request.url.params["columns"] == "groups"
            payload = json.loads(request.content)
            assert "password" not in payload
            current["groups"] = payload["groups"]
            writes.append(payload["groups"])
        return httpx.Response(200, json={"status": "ok", "data": current})

    with httpx.Client(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as client:
        sync._set_remote_membership(client, "org", "org/new", current, True)
        sync._set_remote_membership(client, "org", "org/new", current, True)
        sync._set_remote_membership(client, "org", "org/new", current, False)
    assert writes == [["org/existing", "org/new"], ["org/existing"]]


def test_membership_write_refuses_replaced_casdoor_identity():
    def respond(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"status": "ok", "data": {
            "owner": "org", "name": "member", "id": "replacement", "groups": [],
        }})

    with httpx.Client(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValidationError):
            sync._set_remote_membership(client, "org", "org/group", {"name": "member", "id": "original"}, True)
