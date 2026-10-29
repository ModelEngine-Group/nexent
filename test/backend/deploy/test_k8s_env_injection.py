# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated contracts for Kubernetes env file rendering and manifest composition."""

import base64
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


REPO = Path(__file__).resolve().parents[3]
HELPER = REPO / "deploy/k8s/env.sh"
DEPLOY = REPO / "deploy/k8s/deploy.sh"
CHART = REPO / "deploy/k8s/helm/nexent"
BACKENDS = ("config", "runtime", "mcp", "northbound", "data-process")
TEST_JWT_SECRET = "synthetic-test-only-jwt-signing-key-never-for-deployment"


def render_data(path, extra_environment=None):
    environment = os.environ.copy()
    environment.update(extra_environment or {})
    return subprocess.run(
        ["bash", "-c", 'source "$1"; k8s_env_file_data "$2"', "env-test", str(HELPER), str(path)],
        env=environment, capture_output=True, text=True, check=False,
    )


def decoded_data(output):
    return {key: base64.b64decode(value).decode() for key, value in (yaml.safe_load(output) or {}).items()}


def render_values(root, output, extra_environment=None):
    environment = os.environ.copy()
    environment["JWT_SECRET"] = TEST_JWT_SECRET
    environment.update(extra_environment or {})
    script = r'''
set -e
source "$1" --help >/dev/null
ROOT_ENV_FILE="$2"
DEPLOYMENT_ROOT_ENV="$2"
GENERATED_SECRETS_VALUES="$3"
DEPLOYMENT_COMPONENTS="application,data-process"
DEPLOYMENT_SANDBOX_MODE="${TEST_SANDBOX_MODE:-lightweight}"
MINIO_ACCESS_KEY="final-access"
MINIO_SECRET_KEY="final-secret"
NEXENT_POSTGRES_PASSWORD="final-postgres"
NEXENT_MCP_DOCKER_IMAGE="synthetic/mcp:chosen"
NEXENT_SANDBOX_IMAGE="synthetic/sandbox:chosen"
sql_files_checksum() { printf 'synthetic-sql-checksum'; }
deployment_render_image_rollout_checksums() { printf '    backendImage: "synthetic-image-checksum"\n'; }
render_runtime_secret_values
'''
    return subprocess.run(
        ["bash", "-c", script, "values-test", str(DEPLOY), str(root), str(output)],
        env=environment, capture_output=True, text=True, check=False,
    )


def helm_result(values=None, infrastructure=False, jwt_secret=TEST_JWT_SECRET):
    helm = shutil.which("helm")
    assert helm, "Helm is required for deployment manifest verification"
    chart = CHART.parent / "nexent-infrastructure" if infrastructure else CHART
    command = [helm, "template", "env-test", str(chart)]
    if values:
        for path in values if isinstance(values, (list, tuple)) else [values]:
            command += ["-f", str(path)]
    if not infrastructure and jwt_secret is not None:
        command += ["--set-string", "nexent-common.secrets.jwtSecret=" + jwt_secret]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def helm_documents(values=None, infrastructure=False, jwt_secret=TEST_JWT_SECRET):
    result = helm_result(values, infrastructure, jwt_secret)
    assert result.returncode == 0, result.stderr
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def render_runtime_values(root, output):
    script = 'set -e; source "$1" --help >/dev/null; source "$2"; render_k8s_runtime_config_values "$3"'
    return subprocess.run(
        ["bash", "-c", script, "runtime-test", str(DEPLOY), str(root), str(output)],
        capture_output=True, text=True, check=False,
    )


def container_environment(documents, deployment):
    configmaps = {d["metadata"]["name"]: d.get("data", {}) for d in documents if d["kind"] == "ConfigMap"}
    secrets = {d["metadata"]["name"]: decoded_data(yaml.safe_dump(d.get("data", {})))
               for d in documents if d["kind"] == "Secret"}
    environment = {}
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    for source in container.get("envFrom", []):
        if "configMapRef" in source:
            environment.update(configmaps[source["configMapRef"]["name"]])
        else:
            environment.update(secrets[source["secretRef"]["name"]])
    for variable in container.get("env", []):
        if "value" in variable:
            environment[variable["name"]] = variable["value"]
        else:
            reference = variable["valueFrom"]["configMapKeyRef"]
            environment[variable["name"]] = configmaps[reference["name"]][reference["key"]]
    return container, environment


def test_env_values_preserve_bash_strings_and_only_declared_names(tmp_path):
    root = tmp_path / ".env"
    root.write_text('''
# Synthetic values only.
PLAIN=hello
EMPTY=
BOOLEAN=false
NUMBER=00123
export EXPORTED="some value"
JSON='{"key":"a=b # c","enabled":false}'
LITERAL='$literal "quoted" \\path # ='
MULTILINE="first
ASSIGNMENT_LOOKING=value
last
"
DUPLICATE=old
DUPLICATE=new
EXPANDED="${PLAIN}-suffix"
SUBPROCESS_EXPANDED=$(printenv PLAIN)
UNKNOWN_NEW_FEATURE=enabled
''')
    result = render_data(root, {"HOST_ONLY_SENTINEL": "must-not-leak", "EXPORTED": "host-value"})
    assert result.returncode == 0, result.stderr
    assert decoded_data(result.stdout) == {
        "PLAIN": "hello", "EMPTY": "", "BOOLEAN": "false", "NUMBER": "00123",
        "EXPORTED": "some value", "JSON": '{"key":"a=b # c","enabled":false}',
        "LITERAL": '$literal "quoted" \\path # =',
        "MULTILINE": "first\nASSIGNMENT_LOOKING=value\nlast\n",
        "DUPLICATE": "new", "EXPANDED": "hello-suffix", "SUBPROCESS_EXPANDED": "hello",
        "UNKNOWN_NEW_FEATURE": "enabled",
    }


@pytest.mark.parametrize("content", ["", "# Comments only\n\n"])
def test_empty_file_renders_empty_mapping(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content)
    result = render_data(path)
    assert result.returncode == 0
    assert yaml.safe_load(result.stdout) == {}


@pytest.mark.parametrize("content", [
    'VALID=synthetic-secret\nINVALID="unterminated\n',
    'VALID=synthetic-secret\nfalse\nAFTER=unused\n',
    'VALID=synthetic-secret\ncommand_that_does_not_exist\nAFTER=unused\n',
])
def test_invalid_file_fails_without_partial_data_or_sensitive_diagnostics(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content)
    result = render_data(path)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "failed to load environment file" in result.stderr
    assert "synthetic-secret" not in result.stderr


def test_missing_file_fails(tmp_path):
    result = render_data(tmp_path / "missing.env")
    assert result.returncode != 0
    assert result.stdout == ""


def test_encoder_failure_does_not_publish_partial_values(tmp_path):
    root = tmp_path / ".env"
    root.write_text("FIRST=synthetic\nSECOND=value\n")
    commands = tmp_path / "bin"
    commands.mkdir()
    encoder = commands / "base64"
    encoder.write_text("#!/bin/sh\nexit 1\n")
    encoder.chmod(0o755)
    result = render_data(root, {"PATH": str(commands) + os.pathsep + os.environ["PATH"]})
    assert result.returncode != 0
    assert result.stdout == ""


def test_private_values_preserve_file_scope_and_final_credentials(tmp_path):
    root = tmp_path / ".env"
    root.write_text("SHARED=root\nMINIO_ACCESS_KEY=original\nHITL_ENABLED=true\nEMPTY=\n")
    (tmp_path / "monitoring.env").write_text("SHARED=monitoring\nMONITOR_ONLY=yes\n")
    output = tmp_path / "generated.yaml"
    output.write_text("old: data\n")
    output.chmod(0o644)
    result = render_values(root, output, {"HOST_ONLY_SENTINEL": "must-not-leak", "SHARED": "host"})
    assert result.returncode == 0, result.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    values = yaml.safe_load(output.read_text())
    env_files = values["nexent-common"]["envFiles"]
    assert decoded_data(yaml.safe_dump(env_files["rootData"])) == {
        "SHARED": "root", "MINIO_ACCESS_KEY": "original", "HITL_ENABLED": "true", "EMPTY": "",
    }
    assert decoded_data(yaml.safe_dump(env_files["monitoringData"])) == {
        "SHARED": "monitoring", "MONITOR_ONLY": "yes",
    }
    assert values["nexent-common"]["secrets"]["minio"]["accessKey"] == "final-access"
    assert values["nexent-common"]["secrets"]["jwtSecret"] == TEST_JWT_SECRET
    assert list(tmp_path.glob("generated.yaml.*")) == []


@pytest.mark.parametrize("invalid_input", ["root", "monitoring"])
def test_values_failure_preserves_previous_file(tmp_path, invalid_input):
    root = tmp_path / ".env"
    root.write_text("VALID=synthetic\n")
    invalid = root if invalid_input == "root" else tmp_path / "monitoring.env"
    invalid.write_text('SENSITIVE=synthetic-secret\nBROKEN="unterminated\n')
    output = tmp_path / "generated.yaml"
    output.write_text("previous: intact\n")
    result = render_values(root, output)
    assert result.returncode != 0
    assert output.read_text() == "previous: intact\n"
    assert "synthetic-secret" not in result.stdout + result.stderr


def test_fresh_values_remove_keys_and_track_effective_changes(tmp_path):
    root = tmp_path / ".env"
    root.write_text("REMOVED=old\nCHANGED=old\nEMPTY=\n")
    output = tmp_path / "generated.yaml"
    assert render_values(root, output).returncode == 0
    first = yaml.safe_load(output.read_text())
    root.write_text("EMPTY=\nNEW=added\nCHANGED=new\n")
    assert render_values(root, output).returncode == 0
    second = yaml.safe_load(output.read_text())
    assert decoded_data(yaml.safe_dump(second["nexent-common"]["envFiles"]["rootData"])) == {
        "EMPTY": "", "NEW": "added", "CHANGED": "new",
    }
    assert second["nexent-common"]["envFiles"]["monitoringData"] == {}
    assert first["global"]["rolloutChecksums"]["env"] != second["global"]["rolloutChecksums"]["env"]
    root.write_text("# Reorder only\nCHANGED=new\n\nEMPTY=\nNEW=added\n")
    assert render_values(root, output).returncode == 0
    third = yaml.safe_load(output.read_text())
    assert second["global"]["rolloutChecksums"]["env"] == third["global"]["rolloutChecksums"]["env"]
    assert render_values(root, output, {"TEST_SANDBOX_MODE": "disabled"}).returncode == 0
    fourth = yaml.safe_load(output.read_text())
    assert third["global"]["rolloutChecksums"]["env"] != fourth["global"]["rolloutChecksums"]["env"]


def test_default_helm_has_empty_env_secrets_and_service_specific_references():
    documents = helm_documents()
    secrets = {d["metadata"]["name"]: d for d in documents if d["kind"] == "Secret"}
    assert secrets["nexent-env"]["data"] == {}
    assert secrets["nexent-monitoring-env"]["data"] == {}
    assert decoded_data(yaml.safe_dump(secrets["nexent-secrets"]["data"]))["JWT_SECRET"] == TEST_JWT_SECRET
    for deployment in [d for d in documents if d["kind"] == "Deployment"]:
        name = deployment["metadata"]["name"].removeprefix("nexent-")
        references = [v.get("secretRef", {}).get("name")
                      for v in deployment["spec"]["template"]["spec"]["containers"][0].get("envFrom", [])]
        if name in BACKENDS:
            expected = [None, "nexent-env"]
            if name in ("config", "runtime"):
                expected.append("nexent-monitoring-env")
            assert references == expected + ["nexent-secrets"]
            assert container_environment(documents, deployment)[1]["JWT_SECRET"] == TEST_JWT_SECRET
        else:
            assert "nexent-env" not in references
            assert "nexent-monitoring-env" not in references
    for document in helm_documents(infrastructure=True):
        if document["kind"] == "Deployment":
            for container in document["spec"]["template"]["spec"]["containers"]:
                assert all(source.get("secretRef", {}).get("name") not in
                           ("nexent-env", "nexent-monitoring-env") for source in container.get("envFrom", []))


@pytest.mark.parametrize("jwt_secret", [None, ""])
def test_application_helm_rejects_missing_or_empty_jwt_secret(jwt_secret):
    result = helm_result(jwt_secret=jwt_secret)
    assert result.returncode != 0
    assert "secrets.jwtSecret is required for local authentication" in result.stderr
    assert TEST_JWT_SECRET not in result.stdout + result.stderr


def test_generated_signing_key_changes_auth_rollout_checksum(tmp_path):
    root = tmp_path / ".env"
    root.write_text("UNCHANGED=value\n")
    output = tmp_path / "generated.yaml"
    assert render_values(root, output).returncode == 0
    first = yaml.safe_load(output.read_text())
    changed_key = TEST_JWT_SECRET + "-rotated"
    assert render_values(root, output, {"JWT_SECRET": changed_key}).returncode == 0
    second = yaml.safe_load(output.read_text())
    assert second["nexent-common"]["secrets"]["jwtSecret"] == changed_key
    assert first["global"]["rolloutChecksums"]["authSecret"] != second["global"]["rolloutChecksums"]["authSecret"]
    documents = helm_documents(output, jwt_secret=None)
    deployment = next(d for d in documents if d["kind"] == "Deployment" and d["metadata"]["name"] == "nexent-config")
    assert container_environment(documents, deployment)[1]["JWT_SECRET"] == changed_key


def test_runtime_mapping_preserves_web_specific_configuration(tmp_path):
    root = tmp_path / ".env"
    root.write_text("TZ=Etc/UTC\nFILE_UPLOAD_SIZE_LIMIT=23\nNORTHBOUND_API_SERVER=http://synthetic-northbound:5013/api\n")
    output = tmp_path / "runtime.yaml"
    result = render_runtime_values(root, output)
    assert result.returncode == 0, result.stderr
    documents = helm_documents(output)
    deployments = [d for d in documents if d["kind"] == "Deployment" and
                   d["metadata"]["name"].removeprefix("nexent-") in (*BACKENDS, "web")]
    for deployment in deployments:
        _, effective = container_environment(documents, deployment)
        assert effective["TZ"] == "Etc/UTC"
        if deployment["metadata"]["name"] == "nexent-web":
            assert effective["FILE_UPLOAD_SIZE_LIMIT"] == "23"
            assert effective["NORTHBOUND_API_SERVER"] == "http://synthetic-northbound:5013/api"


def test_backend_configuration_uses_secret_without_fixed_runtime_copies(tmp_path):
    root = tmp_path / ".env"
    expected = {
        "CAS_DEFAULT_TENANT_ID": "synthetic-tenant", "CAS_DEFAULT_ROLE": "ADMIN",
        "CAS_HEARTBEAT_INTERVAL_SECONDS": "71", "GITHUB_OAUTH_CLIENT_SECRET": "synthetic-oauth",
        "TOKEN": "synthetic-voice", "DP_PARSE_THREADS_PER_PROCESS": "5",
        "CLIP_MODEL_PATH": "/synthetic/model", "SKILLS_PATH": "/synthetic/skills",
        "RUNTIME_AGENT_THREAD_MAX_WORKERS": "17", "UNKNOWN_NEW_FEATURE": "enabled",
        "CAS_ROLE_MAP_JSON": '{"team":"ADMIN"}', "CAS_SERVER_URL": "",
    }
    root.write_text("\n".join(key + "='" + value + "'" for key, value in expected.items()) + "\n")
    runtime = tmp_path / "runtime.yaml"
    secrets = tmp_path / "secrets.yaml"
    assert render_runtime_values(root, runtime).returncode == 0
    assert render_values(root, secrets).returncode == 0
    common = yaml.safe_load(runtime.read_text())["nexent-common"]["config"]
    assert common == {
        "timezone": "Asia/Shanghai", "services": {"northboundServer": "http://nexent-northbound:5013/api"},
        "redis": {"url": "redis://nexent-redis:6379/0"}, "dataProcess": {"partProcessorCount": "3"},
    }
    documents = helm_documents([runtime, secrets], jwt_secret=None)
    configmap = next(d for d in documents if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "nexent-config")
    assert configmap["data"]["CAS_DEFAULT_TENANT_ID"] == "tenant_id"
    assert configmap["data"]["GITHUB_OAUTH_CLIENT_SECRET"] == ""
    for deployment in [d for d in documents if d["kind"] == "Deployment" and
                       d["metadata"]["name"].removeprefix("nexent-") in BACKENDS]:
        _, effective = container_environment(documents, deployment)
        for key, value in expected.items():
            assert effective[key] == value
        assert effective["MINIO_ACCESS_KEY"] == "final-access"

    # Removing an override restores the Chart fallback through a fresh Secret map.
    root.write_text("UNKNOWN_NEW_FEATURE=enabled\n")
    assert render_runtime_values(root, runtime).returncode == 0
    assert render_values(root, secrets).returncode == 0
    documents = helm_documents([runtime, secrets], jwt_secret=None)
    deployment = next(d for d in documents if d["kind"] == "Deployment" and d["metadata"]["name"] == "nexent-config")
    _, effective = container_environment(documents, deployment)
    assert effective["CAS_DEFAULT_TENANT_ID"] == "tenant_id"
    assert effective["GITHUB_OAUTH_CLIENT_SECRET"] == ""
    assert effective["CLIP_MODEL_PATH"] == "/opt/models/clip-vit-base-patch32"


@pytest.mark.parametrize("count,redis_url", [("7", "redis://synthetic:6379/4"), ("0", "")])
def test_cleanup_retains_derived_defaults_and_empty_inputs(tmp_path, count, redis_url):
    root = tmp_path / ".env"
    root.write_text("DP_PART_PROCESSOR_COUNT=" + count + "\nREDIS_URL='" + redis_url + "'\n")
    runtime = tmp_path / "runtime.yaml"
    secrets = tmp_path / "secrets.yaml"
    assert render_runtime_values(root, runtime).returncode == 0
    assert render_values(root, secrets).returncode == 0
    documents = helm_documents([runtime, secrets], jwt_secret=None)
    deployment = next(d for d in documents if d["kind"] == "Deployment" and d["metadata"]["name"] == "nexent-data-process")
    _, effective = container_environment(documents, deployment)
    assert effective["WORKER_CONCURRENCY"] == str(int(count) + 1)
    assert effective["RUNTIME_STATE_REDIS_URL"] == redis_url


def test_direct_helm_configuration_retains_defaults_and_custom_overrides(tmp_path):
    output = tmp_path / "direct-helm.yaml"
    output.write_text(yaml.safe_dump({"nexent-common": {"config": {
        "cas": {"defaultTenantId": "helm-tenant"}, "redis": {"url": "redis://helm:6379/3"},
        "dataProcess": {"partProcessorCount": "6"},
    }}}))
    documents = helm_documents(output)
    deployment = next(d for d in documents if d["kind"] == "Deployment" and d["metadata"]["name"] == "nexent-config")
    _, effective = container_environment(documents, deployment)
    assert effective["CAS_DEFAULT_TENANT_ID"] == "helm-tenant"
    assert effective["RUNTIME_STATE_REDIS_URL"] == "redis://helm:6379/3"
    assert effective["WORKER_CONCURRENCY"] == "7"
    assert effective["CAS_DEFAULT_ROLE"] == "USER"
    assert effective["NORTHBOUND_API_SERVER"] == "http://nexent-northbound:5013/api"


@pytest.mark.parametrize("deployment_version", ["speed", "full"])
@pytest.mark.parametrize("sandbox_mode,level", [("lightweight", "docker"), ("disabled", "local"), ("full", "docker")])
def test_helm_composition_preserves_precedence_and_platform_settings(tmp_path, deployment_version, sandbox_mode, level):
    root = tmp_path / ".env"
    root.write_text("""SHARED=root
MINIO_ACCESS_KEY=original
EMPTY=
UNKNOWN_NEW_FEATURE=enabled
IS_DEPLOYED_BY_KUBERNETES=false
KUBERNETES_NAMESPACE=wrong
DEPLOYMENT_VERSION=wrong
NEXENT_SQL_STARTUP_MODE=wrong
NEXENT_SQL_FILES_CHECKSUM=wrong
NEXENT_MCP_DOCKER_IMAGE=wrong
NEXENT_SANDBOX_DOCKER_IMAGE=wrong
NEXENT_SANDBOX_DEFAULT_LEVEL=wrong
""")
    (tmp_path / "monitoring.env").write_text("SHARED=monitoring\nMONITOR_ONLY=yes\nMINIO_ACCESS_KEY=monitor-credential\n")
    output = tmp_path / "generated.yaml"
    result = render_values(root, output)
    assert result.returncode == 0, result.stderr
    values = yaml.safe_load(output.read_text())
    values["global"].update(namespace="synthetic-namespace", deploymentVersion=deployment_version, sandboxMode=sandbox_mode)
    output.write_text(yaml.safe_dump(values))
    documents = helm_documents(output, jwt_secret=None)
    deployments = [d for d in documents if d["kind"] == "Deployment" and
                   d["metadata"]["name"].removeprefix("nexent-") in BACKENDS]
    assert len(deployments) == 5
    for deployment in deployments:
        name = deployment["metadata"]["name"].removeprefix("nexent-")
        container, effective = container_environment(documents, deployment)
        assert effective["SHARED"] == ("monitoring" if name in ("config", "runtime") else "root")
        assert ("MONITOR_ONLY" in effective) == (name in ("config", "runtime"))
        assert effective["MINIO_ACCESS_KEY"] == "final-access"
        assert effective["EMPTY"] == ""
        assert effective["UNKNOWN_NEW_FEATURE"] == "enabled"
        assert effective["IS_DEPLOYED_BY_KUBERNETES"] == "true"
        assert effective["KUBERNETES_NAMESPACE"] == "synthetic-namespace"
        assert effective["DEPLOYMENT_VERSION"] == deployment_version
        assert effective["NEXENT_SQL_STARTUP_MODE"] == {"config": "migrate", "data-process": "off"}.get(name, "wait")
        assert effective["NEXENT_SQL_FILES_CHECKSUM"] == "synthetic-sql-checksum"
        assert effective["NEXENT_MCP_DOCKER_IMAGE"] == "nexent/nexent-mcp:latest"
        assert effective["NEXENT_SANDBOX_DOCKER_IMAGE"] == "nexent/nexent-sandbox:latest"
        assert effective["NEXENT_SANDBOX_DEFAULT_LEVEL"] == level
        assert effective["TZ"] == "Asia/Shanghai"
        names = [v["name"] for v in container["env"]]
        assert len(names) == len(set(names))
        assert deployment["spec"]["template"]["metadata"]["annotations"]["checksum/nexent-env"] == values["global"]["rolloutChecksums"]["env"]
