# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manual legacy recovery guards and exact-scope teardown contracts."""

from pathlib import Path

import pytest
import yaml

from deploy.sql.tools.supabase_to_postgres import migrate_docker as stack
from deploy.sql.tools.supabase_to_postgres.migrate_docker import MigrationSetupError


@pytest.fixture
def config(mocker):
    mocker.patch.object(Path, "is_file", return_value=True)
    return {"SUPABASE_DATA_DIR": str(Path.cwd() / "original-data"),
            "SUPABASE_POSTGRES_PASSWORD": "private-password"}


def test_missing_data_refuses_to_create_any_container(config, mocker):
    mocker.patch.object(Path, "is_file", return_value=False)
    docker = mocker.patch.object(stack, "docker")
    with pytest.raises(MigrationSetupError, match="PG_VERSION"):
        stack.execute("up", config)
    docker.assert_not_called()


def test_missing_containers_restore_only_database_by_default(config, mocker):
    docker = mocker.patch.object(stack, "docker", side_effect=["", ""])
    stack.execute("up", config)
    args, env = docker.call_args.args
    assert args[0] == "compose" and args[-3:] == ["up", "-d", "db"]
    assert "legacy-auth" not in args and "--remove-orphans" not in args
    assert env["SUPABASE_POSTGRES_PASSWORD"] == "private-password"
    assert env["SUPABASE_DATA_DIR"] == config["SUPABASE_DATA_DIR"]


def test_full_stack_requires_original_auth_keys(config, mocker):
    docker = mocker.patch.object(stack, "docker")
    with pytest.raises(MigrationSetupError, match="original JWT_SECRET"):
        stack.execute("up", config, with_auth=True)
    docker.assert_not_called()


def test_full_stack_and_production_overlay(config, mocker):
    docker = mocker.patch.object(stack, "docker", side_effect=["", ""])
    stack.execute("up", {**config,"JWT_SECRET":"signing", "SUPABASE_KEY":"anon", "SERVICE_ROLE_KEY":"service", "DASHBOARD_PASSWORD":"dashboard"},
                  with_auth=True, production=True)
    args, _ = docker.call_args.args
    assert args[-5:] == ["up", "-d", "db", "auth", "kong"]
    assert "legacy-auth" in args
    assert str(stack.HERE / "docker-compose-supabase.prod.yml") in args


@pytest.mark.parametrize("running", ["true", "false"])
def test_existing_container_is_reused_without_recreation(config, mocker, running):
    docker = mocker.patch.object(stack, "docker", side_effect=["supabase-db-mini\n", running, ""])
    stack.execute("up", config)
    commands = [call.args[0][0] for call in docker.call_args_list]
    assert commands == (["ps", "inspect"] if running == "true" else ["ps", "inspect", "start"])


def test_mixed_container_set_requires_explicit_teardown(config, mocker):
    docker = mocker.patch.object(stack, "docker", return_value="supabase-db-mini\n")
    with pytest.raises(MigrationSetupError, match="down then up"):
        stack.execute("up", {**config,"JWT_SECRET":"signing", "SUPABASE_KEY":"anon", "SERVICE_ROLE_KEY":"service", "DASHBOARD_PASSWORD":"dashboard"},with_auth=True)
    docker.assert_called_once()


def test_down_removes_only_legacy_containers_and_owned_network(mocker):
    docker = mocker.patch.object(stack, "docker", side_effect=[
        "supabase-db-mini\nnexent-postgresql\n", "false", "", "nexent_supabase_migration\nnexent_network\n",
        "nexent-supabase-migration", ""])
    stack.execute("down", {})
    args = [call.args[0] for call in docker.call_args_list]
    assert ["rm", "supabase-db-mini"] in args
    assert ["network", "rm", "nexent_supabase_migration"] in args
    assert all("nexent-postgresql" not in item and "-v" not in item for item in args)
    assert not any(item[0] == "compose" for item in args)


def test_shared_or_foreign_network_is_not_removed(mocker):
    docker = mocker.patch.object(stack, "docker", side_effect=["", "nexent_supabase_migration\n", "other-project"])
    stack.execute("down", {})
    assert not any(call.args[0][:2] == ["network", "rm"] for call in docker.call_args_list)


def test_invalid_or_nonlegacy_names_rejected_before_docker(mocker):
    docker = mocker.patch.object(stack, "docker")
    with pytest.raises(MigrationSetupError):
        stack.execute("down", {"SUPABASE_MIGRATION_DB_CONTAINER":"nexent-postgresql"})
    docker.assert_not_called()


def test_compose_data_bind_and_sql_references_are_valid():
    content = yaml.safe_load((stack.HERE / "docker-compose-supabase.yml").read_text(encoding="utf-8"))
    db = content["services"]["db"]
    bind = next(item for item in db["volumes"] if isinstance(item,dict))
    assert bind["bind"]["create_host_path"] is False
    assert "SUPABASE_DATA_DIR:?" in bind["source"]
    for item in db["volumes"]:
        if isinstance(item,str) and item.startswith("../../supabase/"):
            assert (stack.HERE / item.split(":")[0]).is_file()
    assert content["services"]["auth"]["profiles"] == ["legacy-auth"]
    assert content["services"]["kong"]["profiles"] == ["legacy-auth"]
    assert content["networks"]["nexent"]["name"] != "nexent_network"
