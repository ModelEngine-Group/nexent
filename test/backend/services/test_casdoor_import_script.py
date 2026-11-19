# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for the operator's Casdoor import command."""

import json
import os
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from consts import const as settings
from contracts.constants import environment
from management.services.permission.identity import casdoor_groups as directory
from scripts import import_nexent_to_casdoor as migration


def group(group_id, parent=None):
    return SimpleNamespace(group_id=group_id, parent_group_id=parent, group_name=f"group-{group_id}",
                           group_description=None, casdoor_scope=None, casdoor_group_key=None)


def test_group_order_uses_existing_parent_and_rejects_missing_or_cyclic_parent():
    assert [item.group_id for item in migration.ordered_groups({2: group(2, 1), 1: group(1, 9)}, {9})] == [1, 2]
    for groups in ({1: group(1, 9)}, {1: group(1, 2), 2: group(2, 1)}):
        with pytest.raises(migration.ImportConflict, match="cycle or a parent"):
            list(migration.ordered_groups(groups, {}))


@pytest.mark.skipif(os.name != "posix", reason="Private apply journal uses POSIX permissions")
def test_journal_persists_distinct_passwords_and_checks_scope_and_permissions(tmp_path):
    path = tmp_path / "credentials.json"
    journal = migration.create_journal(path, ["scope", "tenant"], {
        "u1": ("a@example.test", "ADMIN"), "u2": ("b@example.test", "USER"),
    }, {}, {"ADMIN": "nexent-admin", "USER": "nexent-user"})
    assert path.stat().st_mode & 0o777 == 0o600
    assert migration.read_journal(path, ["scope", "tenant"]) == journal
    assert len({user["temporary_password"] for user in journal["users"].values()}) == 2
    with pytest.raises(migration.ImportConflict, match="different tenant"):
        migration.read_journal(path, ["scope", "other"])
    path.chmod(0o644)
    with pytest.raises(migration.ImportConflict, match="mode 0600"):
        migration.read_journal(path, ["scope", "tenant"])


def test_remote_conflict_never_grants_role_or_writes_binding():
    collaborator = Mock()
    collaborator._request.return_value = {"id": "other"}
    session = Mock()
    saved = {"id": "expected", "username": "name", "email": "a@example.test"}
    with pytest.raises(migration.ImportConflict, match="differs from its recovery record"):
        migration.import_users(session, None, "org", "tenant", {"u": (saved["email"], "ADMIN")},
                               {}, {"users": {"u": saved}}, collaborator, {"ADMIN": "nexent-admin"})
    assert collaborator._request.call_count == 1
    session.add.assert_not_called()


def test_role_mapping_uses_configured_name_without_guessing_between_roles():
    assert migration.mapped_role_name("DEV", {"developers": "DEV"}) == "developers"
    assert migration.mapped_role_name("DEV", {"developers": "DEV", "nexent-developer": "DEV"}) == "nexent-developer"
    with pytest.raises(migration.ImportConflict, match="unambiguous"):
        migration.mapped_role_name("DEV", {"developers": "DEV", "dev-team": "DEV"})


def test_preview_only_reads_the_configured_target(monkeypatch, capsys):
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://casdoor.example")
    monkeypatch.setattr(settings, "CASDOOR_ROLE_SYNC_ORGANIZATION", "org")
    monkeypatch.setattr(settings, "CASDOOR_ROLE_MAP_JSON", '{"nexent-admin":"ADMIN"}')
    monkeypatch.setattr(environment, "CASDOOR_GROUP_SYNC_TENANT_ID", "tenant")
    monkeypatch.setattr(environment, "OAUTH_SSL_VERIFY", True)
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "NEXENT_POSTGRES_PASSWORD"):
        monkeypatch.setattr(environment, key, "synthetic")
    monkeypatch.setattr(directory, "_directory", lambda _: nullcontext((None, None, "org")))
    monkeypatch.setattr(directory, "_request", lambda *args, **kwargs: {
        "owner": "org", "name": "nexent-admin", "isEnabled": True,
    })
    monkeypatch.setattr(migration, "plan_import",
                        lambda *args: ({"u": ("a@example.test", "ADMIN")}, {}, [], {}, {}, 0))
    for write in ("create_journal", "import_users", "import_groups"):
        monkeypatch.setattr(migration, write, Mock(side_effect=AssertionError("Preview wrote data")))
    args = SimpleNamespace(tenant="tenant", organization="org", apply=False, credentials_file=None)
    migration.run(args)
    assert "New users: 1 (1 tenant administrators)" in capsys.readouterr().out
    args.organization = "built-in"
    with pytest.raises(migration.ImportConflict, match="business group sync target"):
        migration.run(args)


def test_apply_and_resume_keep_group_ids_and_existing_memberships():
    org = "org"
    account = {"id": "stable", "email": "a@example.test", "username": "nexent-account",
               "temporary_password": "synthetic-test-password"}
    users = {}
    remote_groups = {}
    role = {"owner": org, "name": "nexent-admin", "isEnabled": True, "users": ["org/previous"]}
    operations = []

    def respond(request):
        operation = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content) if request.content else None
        if request.method == "POST":
            operations.append(operation)
        data = None
        if operation == "get-user":
            data = users.get(request.url.params["id"])
        elif operation == "add-user":
            assert payload["needUpdatePassword"] is True
            assert not payload.get("isAdmin")
            users[f"{org}/{payload['name']}"] = {
                key: value for key, value in payload.items() if key != "password"
            } | {"groups": ["org/keep"]}
        elif operation == "get-role":
            data = role
        elif operation == "update-role":
            assert request.url.params["columns"] == "users"
            role.update(payload)
        elif operation == "get-groups":
            data = list(remote_groups.values())
        elif operation == "add-group":
            remote_groups[payload["name"]] = payload
        elif operation == "update-user":
            assert request.url.params["columns"] == "groups"
            users[request.url.params["id"]]["groups"] = payload["groups"]
        else:
            pytest.fail(operation)
        return httpx.Response(200, json={"status": "ok", "data": data})

    journal = {"batch": "example", "users": {"u": account}}
    g1, g2 = group(10), group(11, 10)
    with httpx.Client(base_url="https://casdoor.example", transport=httpx.MockTransport(respond)) as client:
        for expected_writes in (5, 0):
            before = len(operations)
            session = Mock()
            bound = {}
            migration.import_users(session, client, org, "tenant", {"u": (account["email"], "ADMIN")},
                                   bound, journal, directory, {"ADMIN": "nexent-admin"})
            migration.import_groups(client, org, [g1, g2], {}, {10: set(), 11: {"u"}},
                                    bound, journal, directory)
            assert len(operations) - before == expected_writes
            assert session.add.call_args.args[0].user_id == "u"
            assert session.add.call_args.args[0].provider_username == account["username"]

    assert role["users"] == ["org/previous", "org/nexent-account"]
    assert g1.group_id == 10 and g2.group_id == 11
    assert g1.casdoor_group_key.startswith("nexent-import-example-10/")
    assert g2.casdoor_group_key.startswith("nexent-import-example-11/")
    assert remote_groups["nexent-import-example-11"]["parentId"] == "nexent-import-example-10"
    assert users["org/nexent-account"]["groups"] == ["org/keep", "org/nexent-import-example-11"]
