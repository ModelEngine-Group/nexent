# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway deployments consume the shared PostgreSQL ConfigMap and Secret."""

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
DB_KEYS = {"POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "NEXENT_POSTGRES_PASSWORD"}


@pytest.mark.parametrize("standalone", [False, True])
def test_helm_gateway_uses_existing_database_config_and_secret(tmp_path, standalone):
    if standalone:
        chart = tmp_path / "nexent-gateway"
        shutil.copytree(CHART / "nexent-gateway", chart)
        shutil.copytree(CHART / "nexent-common", tmp_path / "nexent-common")
        subprocess.run(["helm", "dependency", "build", str(chart)], capture_output=True, text=True, check=True)
    else:
        chart = CHART.parent
    def render(password):
        values = tmp_path / "values.yaml"
        values.write_text(yaml.safe_dump({"global": {"namespace": "nexent"}, "nexent-common": {
            "config": {"postgres": dict(host="existing-db", port="5544", db="existing", user="existing-user")},
            "secrets": dict(jwtSecret="fixture-jwt", postgresPassword=password)}}), encoding="utf-8")
        result = subprocess.run(["helm", "template", "fixture", str(chart), "-f", str(values)], capture_output=True, text=True, check=True)
        docs = [item for item in yaml.safe_load_all(result.stdout) if item]
        config = next(item["data"] for item in docs if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "nexent-config")
        secret = next(item["data"] for item in docs if item["kind"] == "Secret" and item["metadata"]["name"] == "nexent-secrets")
        pod = next(item["spec"]["template"] for item in docs if item["kind"] == "Deployment" and item["metadata"]["name"] == "nexent-gateway")
        env = {item["name"]: item for item in pod["spec"]["containers"][0]["env"]}
        for key in DB_KEYS - {"NEXENT_POSTGRES_PASSWORD"}:
            assert env[key]["valueFrom"]["configMapKeyRef"]["key"] == key
        assert env["NEXENT_POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "NEXENT_POSTGRES_PASSWORD"
        assert not any(key.startswith("GATEWAY_") and "DB" in key for key in env | config | secret)
        return config, secret
    config, secret = render("existing-secret")
    assert [config[key] for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER")] == ["existing-db", "5544", "existing", "existing-user"]
    assert base64.b64decode(secret["NEXENT_POSTGRES_PASSWORD"]).decode() == "existing-secret"
    assert base64.b64decode(render("rotated-secret")[1]["NEXENT_POSTGRES_PASSWORD"]).decode() == "rotated-secret"


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.gateway.yml"])
def test_compose_passes_only_shared_postgresql_settings(filename):
    service = yaml.safe_load((ROOT / "deploy/docker/compose" / filename).read_text(encoding="utf-8"))["services"]["nexent-gateway"]
    expected = dict(POSTGRES_HOST="${POSTGRES_HOST:-nexent-postgresql}", POSTGRES_PORT="${POSTGRES_PORT:-5432}",
        POSTGRES_DB="${POSTGRES_DB:-nexent}", POSTGRES_USER="${POSTGRES_USER:-root}",
        NEXENT_POSTGRES_PASSWORD="${NEXENT_POSTGRES_PASSWORD:?PostgreSQL password is required}")
    for key, value in expected.items():
        assert service["environment"][key] == value
    assert not any(key.startswith("GATEWAY_") and "DB" in key for key in service["environment"])


def test_k8s_password_rotation_uses_shared_postgres_checksum():
    source = (ROOT / "deploy/k8s/deploy.sh").read_text(encoding="utf-8")
    common = (ROOT / "deploy/common/common.sh").read_text(encoding="utf-8")
    def function(text, name):
        return re.search(r"^" + name + r"\(\) \{.*?^\}", text, re.M | re.S).group()
    script = "\n".join([function(source, "env_or_default"), function(source, "yaml_quote"),
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
        env = {**os.environ, "NEXENT_POSTGRES_PASSWORD": password, "JWT_SECRET": "fixture-jwt",
               "ROOT_ENV_FILE": "fixture", "GENERATED_SECRETS_VALUES": "fixture"}
        result = subprocess.run([bash, "-c", script], env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        return yaml.safe_load(result.stdout)
    first, rotated = render("existing-secret"), render("rotated-secret")
    assert first["global"]["rolloutChecksums"]["postgresSecret"] == hashlib.sha256(b"existing-secret").hexdigest()
    assert first["global"]["rolloutChecksums"]["postgresSecret"] != rotated["global"]["rolloutChecksums"]["postgresSecret"]
    assert first["nexent-common"]["secrets"]["postgresPassword"] == "existing-secret"



def test_k8s_runtime_renderer_passes_existing_postgres_values(tmp_path):
    source = (ROOT / "deploy/k8s/deploy.sh").read_text(encoding="utf-8")
    def function(name):
        return re.search(r"^" + name + r"\(\) \{.*?^\}", source, re.M | re.S).group()
    script = "\n".join(function(name) for name in ("yaml_quote", "env_or_default", "render_k8s_runtime_config_values"))
    script += '\nrender_k8s_runtime_config_values "$FIXTURE_OUTPUT"'
    (tmp_path / "sql/migrations").mkdir(parents=True)
    init_file = tmp_path / "sql/init.sql"
    init_file.write_text("-- fixture", encoding="utf-8")
    output = tmp_path / "values.yaml"
    env = {**os.environ, "SQL_INIT_FILE": init_file.as_posix(), "DEPLOY_ROOT": tmp_path.as_posix(),
           "FIXTURE_OUTPUT": output.as_posix(), "POSTGRES_HOST": "existing-db", "POSTGRES_PORT": "5544",
           "POSTGRES_DB": "existing", "POSTGRES_USER": "existing-user"}
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    result = subprocess.run([bash, "-c", script], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    config = yaml.safe_load(output.read_text(encoding="utf-8"))["nexent-common"]["config"]
    assert config["postgres"] == dict(host="existing-db", port="5544", db="existing", user="existing-user")
    assert set(config) == {"timezone", "postgres", "services", "redis", "dataProcess"}
