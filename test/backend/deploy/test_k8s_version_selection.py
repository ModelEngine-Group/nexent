# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression contracts for current-version selection in Kubernetes deployment."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml


REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "deploy/k8s/deploy.sh"
CURRENT_VERSION = (REPO / "VERSION").read_text().strip()


def resolve_options(options, *arguments):
    environment = os.environ.copy()
    environment.update(DEPLOYMENT_LANG="en", NEXENT_DEPLOY_CONFIG_MODE="defaults")
    script = r'''
set -e
source "$1" --help "${@:3}" >/dev/null
DEPLOY_OPTIONS_FILE="$2"
ORIGINAL_ARGS=(--defaults --local-config "$2" "${@:3}")
apply_deployment_common_config >/dev/null
printf 'app_version: %s\nshared_version: %s\npersistence_mode: %s\nstorage_class: %s\n' \
    "$APP_VERSION" "$DEPLOYMENT_APP_VERSION" "$PERSISTENCE_MODE" "$STORAGE_CLASS_NAME"
'''
    result = subprocess.run(
        ["bash", "-c", script, "k8s-version-test", str(DEPLOY), str(options), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)


@pytest.mark.parametrize("saved_format", ["yaml", "legacy"])
def test_saved_version_does_not_override_current_repository_version(tmp_path, saved_format):
    options = tmp_path / "deploy.options"
    if saved_format == "yaml":
        options.write_text('k8s:\n  appVersion: "v2.5.0"\n  persistenceMode: "dynamic"\n'
                           '  storageClassName: "synthetic-storage"\n')
    else:
        options.write_text('APP_VERSION="v2.5.0"\nPERSISTENCE_MODE="dynamic"\n'
                           'STORAGE_CLASS_NAME="synthetic-storage"\n')

    actual = resolve_options(options)

    assert actual["app_version"] == CURRENT_VERSION
    assert actual["shared_version"] == CURRENT_VERSION
    assert actual["persistence_mode"] == "dynamic"
    assert actual["storage_class"] == "synthetic-storage"


@pytest.mark.parametrize("argument", ["--version", "--app-version"])
@pytest.mark.parametrize("version", ["v9.8.7", "latest"])
def test_explicit_version_wins_over_saved_and_repository_versions(tmp_path, argument, version):
    options = tmp_path / "deploy.options"
    options.write_text('k8s:\n  appVersion: "v2.5.0"\n')

    actual = resolve_options(options, argument, version)

    assert actual["app_version"] == version
    assert actual["shared_version"] == version


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_empty_saved_options_use_current_repository_version(tmp_path, exists):
    options = tmp_path / "deploy.options"
    if exists:
        options.write_text("")

    actual = resolve_options(options)

    assert actual["app_version"] == CURRENT_VERSION
    assert actual["shared_version"] == CURRENT_VERSION


def test_persisted_options_do_not_pin_an_application_version(tmp_path):
    options = tmp_path / "deploy.options"
    script = r'''
set -e
source "$1" --help >/dev/null
DEPLOY_OPTIONS_FILE="$2"
APP_VERSION="v2.5.0"
DEPLOYMENT_COMPONENTS="infrastructure,application"
DEPLOYMENT_PORT_POLICY="development"
DEPLOYMENT_IMAGE_SOURCE="general"
DEPLOYMENT_SANDBOX_MODE="lightweight"
DEPLOYMENT_MONITORING_PROVIDER="phoenix"
DEPLOYMENT_HTTPS_MODE="disabled"
IS_MAINLAND_SAVED="N"
VERSION_CHOICE_SAVED="speed"
persist_deploy_options
'''
    result = subprocess.run(
        ["bash", "-c", script, "k8s-persist-test", str(DEPLOY), str(options)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    persisted = yaml.safe_load(options.read_text())
    assert "appVersion" not in persisted
    assert "appVersion" not in persisted["k8s"]
    assert persisted["k8s"]["persistenceMode"] == "local"
    assert persisted["components"] == ["infrastructure", "application"]
