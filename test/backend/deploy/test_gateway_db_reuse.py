# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Rendered deployment contracts for shared and independently overridden DB logins."""

import base64
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "deploy/k8s/helm/nexent/charts"


@pytest.mark.parametrize("override", [False, True])
def test_direct_helm_reuses_postgres_and_allows_independent_overrides(tmp_path, override):
    chart = tmp_path / "nexent-gateway"
    shutil.copytree(CHART / "nexent-gateway", chart)
    shutil.copytree(CHART / "nexent-common", tmp_path / "nexent-common")
    subprocess.run(["helm", "dependency", "build", str(chart)], capture_output=True, text=True, check=True)
    def render(password):
        common = dict(config=dict(postgres=dict(host="existing-db", port="5544", db="existing", user="existing-user")),
                      secrets=dict(jwtSecret="fixture-jwt", postgresPassword=password))
        if override:
            common["config"]["gatewayIdentity"] = dict(host="reader-db", port="5545", db="identities", user="reader")
            common["secrets"]["gatewayDatabasePassword"] = "reader-secret"
        values = tmp_path / "values.yaml"
        values.write_text(yaml.safe_dump({"global": {"namespace": "nexent"}, "nexent-common": common}), encoding="utf-8")
        result = subprocess.run(["helm", "template", "fixture", str(chart), "-f", str(values)], capture_output=True, text=True, check=True)
        docs = [item for item in yaml.safe_load_all(result.stdout) if item]
        config = next(item["data"] for item in docs if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "nexent-config")
        secret = next(item["data"] for item in docs if item["kind"] == "Secret" and item["metadata"]["name"] == "nexent-secrets")
        pod = next(item["spec"]["template"] for item in docs if item["kind"] == "Deployment")
        return config, secret, pod["metadata"]["annotations"]
    config, secret, annotations = render("existing-secret")
    assert [config["GATEWAY_DB_" + key] for key in ("HOST", "PORT", "NAME", "USER")] == (
        ["reader-db", "5545", "identities", "reader"] if override else ["existing-db", "5544", "existing", "existing-user"])
    assert base64.b64decode(secret["GATEWAY_DB_PASSWORD"]).decode() == ("reader-secret" if override else "existing-secret")
    assert base64.b64decode(render("rotated-secret")[1]["GATEWAY_DB_PASSWORD"]).decode() == ("reader-secret" if override else "rotated-secret")


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.gateway.yml"])
def test_compose_db_defaults_reference_existing_configuration(filename):
    service = yaml.safe_load((ROOT / "deploy/docker/compose" / filename).read_text(encoding="utf-8"))["services"]["nexent-gateway"]
    expected = {"HOST": "${GATEWAY_DB_HOST:-${POSTGRES_HOST:-nexent-postgresql}}",
                "PORT": "${GATEWAY_DB_PORT:-${POSTGRES_PORT:-5432}}",
                "NAME": "${GATEWAY_DB_NAME:-${POSTGRES_DB:-nexent}}",
                "USER": "${GATEWAY_DB_USER:-${POSTGRES_USER:-root}}",
                "PASSWORD": "${GATEWAY_DB_PASSWORD:-${NEXENT_POSTGRES_PASSWORD:?PostgreSQL password is required}}"}
    for name, value in expected.items():
        assert service["environment"]["GATEWAY_DB_" + name] == value


@pytest.mark.parametrize("override", ["", "reader-secret"])
def test_k8s_secret_renderer_hashes_the_effective_password(override):
    source = (ROOT / "deploy/k8s/deploy.sh").read_text(encoding="utf-8")
    common = (ROOT / "deploy/common/common.sh").read_text(encoding="utf-8")
    def function(text, name):
        return re.search(r"^" + name + r"\(\) \{.*?^\}", text, re.M | re.S).group()
    script = "\n".join([function(source, "env_or_default"), function(source, "gateway_database_value"), function(source, "yaml_quote"),
                          function(common, "deployment_sha256_string"), function(source, "render_runtime_secret_values")])
    script += """
k8s_env_file_data() { printf '      {}'; }
deployment_monitoring_env_file() { printf '/nonexistent-gateway-fixture'; }
deployment_env_values_checksum() { printf 'fixture'; }
sql_files_checksum() { printf 'fixture'; }
deployment_render_image_rollout_checksums() { :; }
k8s_write_private_values() { cat; }
render_runtime_secret_values
"""
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    def render(password):
        env = {**os.environ, "GATEWAY_DB_PASSWORD": override, "NEXENT_POSTGRES_PASSWORD": password,
               "JWT_SECRET": "fixture-jwt", "ROOT_ENV_FILE": "fixture", "GENERATED_SECRETS_VALUES": "fixture"}
        result = subprocess.run([bash, "-c", script], env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        return yaml.safe_load(result.stdout)
    first, rotated = render("existing-secret"), render("rotated-secret")
    checksum = first["global"]["rolloutChecksums"]["gatewayDatabase"]
    assert checksum == hashlib.sha256((override or "existing-secret").encode()).hexdigest()
    assert (checksum == rotated["global"]["rolloutChecksums"]["gatewayDatabase"]) is bool(override)
    assert first["nexent-common"]["secrets"]["gatewayDatabasePassword"] == override


@pytest.mark.parametrize("gateway,postgres,expected", [(None, "existing-user", "existing-user"),
    ("", "existing-user", "existing-user"), ("reader", "existing-user", "reader"),
    ("", "", "root"), (None, None, "root")])
def test_k8s_database_value_handles_empty_overrides(gateway, postgres, expected):
    source = (ROOT / "deploy/k8s/deploy.sh").read_text(encoding="utf-8")
    function = re.search(r"^gateway_database_value\(\) \{.*?^\}", source, re.M | re.S).group()
    env = {key: value for key, value in os.environ.items() if key not in {"GATEWAY_DB_USER", "POSTGRES_USER"}}
    if gateway is not None:
        env["GATEWAY_DB_USER"] = gateway
    if postgres is not None:
        env["POSTGRES_USER"] = postgres
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    result = subprocess.run([bash, "-c", function + "\ngateway_database_value GATEWAY_DB_USER POSTGRES_USER root"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


@pytest.mark.parametrize("override", [False, True])
def test_umbrella_helm_uses_shared_common_database_configuration(override):
    args = ["helm", "template", "fixture", str(CHART.parent), "--set", "nexent-common.secrets.jwtSecret=fixture",
            "--set", "nexent-common.config.postgres.user=existing-user",
            "--set", "nexent-common.secrets.postgresPassword=existing-secret"]
    if override:
        args += ["--set", "nexent-common.config.gatewayIdentity.user=reader",
                 "--set", "nexent-common.secrets.gatewayDatabasePassword=reader-secret"]
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    config = next(item["data"] for item in documents if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "nexent-config")
    secret = next(item["data"] for item in documents if item["kind"] == "Secret" and item["metadata"]["name"] == "nexent-secrets")
    assert config["GATEWAY_DB_USER"] == ("reader" if override else "existing-user")
    assert base64.b64decode(secret["GATEWAY_DB_PASSWORD"]).decode() == ("reader-secret" if override else "existing-secret")
