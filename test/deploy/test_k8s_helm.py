import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HELM_ROOT = PROJECT_ROOT / "deploy" / "k8s" / "helm"
APPLICATION_CHART_SOURCE = HELM_ROOT / "nexent"
INFRASTRUCTURE_CHART_SOURCE = HELM_ROOT / "nexent-infrastructure"
WEB_DOCKERFILE = PROJECT_ROOT / "deploy" / "images" / "dockerfiles" / "web" / "Dockerfile"
OFFICIAL_SKILLS_DIR = PROJECT_ROOT / "deploy" / "docker" / "assets" / "official-skills-zip"

APPLICATION_DEPLOYMENTS = {
    "nexent-config",
    "nexent-data-process",
    "nexent-mcp",
    "nexent-northbound",
    "nexent-runtime",
    "nexent-supabase-auth",
    "nexent-supabase-db",
    "nexent-supabase-kong",
    "nexent-web",
}
INFRASTRUCTURE_DEPLOYMENTS = {
    "nexent-elasticsearch",
    "nexent-minio",
    "nexent-postgresql",
    "nexent-redis",
}
THREE_REPLICA_APPLICATIONS = {
    "nexent-web": {"/mnt/nexent"},
}
APPLICATION_SINGLE_REPLICA = {
    "nexent-mcp",
    "nexent-config",
    "nexent-data-process",
    "nexent-northbound",
    "nexent-runtime",
    "nexent-supabase-kong",
    "nexent-supabase-auth",
    "nexent-supabase-db",
}
STARTUP_RECOVERY_DEPLOYMENTS = {
    "nexent-config",
    "nexent-data-process",
    "nexent-northbound",
    "nexent-runtime",
}
APPLICATION_PVCS = {
    "nexent-workspace",
    "nexent-skills",
    "nexent-memory-plugins",
    "nexent-supabase-db",
}
INFRASTRUCTURE_PVCS = {
    "nexent-elasticsearch",
    "nexent-postgresql",
    "nexent-redis",
    "nexent-minio",
}


def _run(
    command: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _run_in_pseudo_tty(
    command: list[str],
    *,
    env: dict[str, str],
    input_text: str,
) -> subprocess.CompletedProcess[str]:
    script = shutil.which("script")
    if script is None:
        pytest.skip("script is required for pseudo-TTY uninstall tests")
    return subprocess.run(
        [script, "-q", "-e", "-c", shlex.join(command), "/dev/null"],
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
        timeout=60,
        env=env,
    )


@pytest.fixture(scope="module")
def chart_dirs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if shutil.which("helm") is None:
        pytest.skip("helm is required for Kubernetes chart tests")

    destination = tmp_path_factory.mktemp("nexent-helm")
    charts = {
        "application": destination / "nexent",
        "infrastructure": destination / "nexent-infrastructure",
    }
    shutil.copytree(APPLICATION_CHART_SOURCE, charts["application"])
    shutil.copytree(INFRASTRUCTURE_CHART_SOURCE, charts["infrastructure"])

    helm_env = os.environ.copy()
    helm_env["HELM_REPOSITORY_CONFIG"] = str(destination / "repositories.yaml")
    helm_env["HELM_REPOSITORY_CACHE"] = str(destination / "repository-cache")
    for chart in charts.values():
        _run(["helm", "dependency", "update", str(chart)], env=helm_env)
    return charts


@pytest.fixture()
def isolated_k8s_project(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    project = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT / "deploy", project / "deploy")
    const_dir = project / "backend" / "consts"
    const_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "backend" / "consts" / "const.py", const_dir / "const.py")
    (project / "deploy" / "k8s" / "deploy.options").unlink(missing_ok=True)
    (project / "deploy" / "env" / ".env").write_text(
        'MINIO_ACCESS_KEY="test-access"\n'
        'MINIO_SECRET_KEY="test-secret"\n'
        'ELASTIC_PASSWORD="nexent@2025"\n'
        'NEXENT_POSTGRES_PASSWORD="nexent@4321"\n',
        encoding="utf-8",
    )

    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    mock_log = tmp_path / "commands.log"
    _write_executable(
        mock_bin / "helm",
        """#!/bin/bash
printf 'helm %s\\n' "$*" >> "$MOCK_LOG"
case "$1" in
  status)
    if [ "$2" = "nexent-infrastructure" ] && [ "${MOCK_INFRA_EXISTS:-false}" = "true" ]; then exit 0; fi
    if [ "$2" = "nexent" ] && [ "${MOCK_APP_EXISTS:-false}" = "true" ]; then exit 0; fi
    exit 1
    ;;
  get)
    if [ "${MOCK_LEGACY_RELEASE:-false}" = "true" ]; then
      printf 'kind: Deployment\\nmetadata:\\n  name: nexent-elasticsearch\\n'
    fi
    exit 0
    ;;
  upgrade|uninstall) exit 0 ;;
esac
exit 0
""",
    )
    _write_executable(
        mock_bin / "kubectl",
        """#!/bin/bash
printf 'kubectl %s\\n' "$*" >> "$MOCK_LOG"
if [ "$1" = "get" ] && [ "$2" = "namespace" ]; then exit 1; fi
if [ "$1" = "get" ] && [ "$2" = "pv" ]; then exit 1; fi
if [ "$1" = "get" ] && [ "$2" = "pods" ]; then
  case "$*" in
    *app=nexent-config*) printf 'nexent-config-test\n'; exit 0 ;;
  esac
fi
if [ "$1" = "get" ] && [ "$2" = "secret" ]; then
  case "$*" in
    *nexent-infrastructure-secrets*ELASTIC_PASSWORD*) printf 'bmV4ZW50QDIwMjU='; exit 0 ;;
  esac
  exit 1
fi
if [ "$1" = "cp" ]; then
  if [ "${MOCK_FAIL_OFFICIAL_COPY:-false}" = "true" ]; then exit 1; fi
  exit 0
fi
if [ "$1" = "rollout" ]; then
  case "$*" in
    *"${MOCK_FAIL_ROLLOUT:-__none__}"*) exit 1 ;;
  esac
  exit 0
fi
if [ "$1" = "exec" ]; then
  if [[ "$*" == *"sha256sum ./*.zip"* ]]; then
    if [ "${MOCK_FAIL_OFFICIAL_CHECKSUM:-false}" = "true" ]; then
      printf 'invalid-checksum  ./invalid.zip\n'
    else
      (cd "$MOCK_OFFICIAL_SKILLS_DIR" && sha256sum ./*.zip | LC_ALL=C sort)
    fi
    exit 0
  fi
  if [[ "$*" == *'if mv "$staging_dir" "$target_dir"; then'* ]]; then
    if [ "${MOCK_FAIL_OFFICIAL_PROMOTE:-false}" = "true" ]; then exit 1; fi
    exit 0
  fi
  case "$*" in
    *_cluster/health*) printf '{"status":"yellow"}'; exit 0 ;;
    *_security/api_key*)
      if [ "${MOCK_FAIL_ES_INIT:-false}" = "true" ]; then printf '{"error":"failed"}'; else printf '{"encoded":"test-api-key"}'; fi
      exit 0
      ;;
    *_security/_authenticate*) printf '200'; exit 0 ;;
  esac
  exit 0
fi
exit 0
""",
    )
    _write_executable(mock_bin / "docker", "#!/bin/bash\nexit 0\n")

    env = os.environ.copy()
    env.pop("ELASTICSEARCH_API_KEY", None)
    env["PATH"] = f"{mock_bin}:{env['PATH']}"
    env["MOCK_LOG"] = str(mock_log)
    env["MOCK_OFFICIAL_SKILLS_DIR"] = str(
        project / "deploy" / "docker" / "assets" / "official-skills-zip"
    )
    env["NEXENT_SYNC_ES_KEY_TO_ENV"] = "false"
    return project, env, mock_log


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _instrument_shell_function(path: Path, function_name: str) -> None:
    content = path.read_text(encoding="utf-8")
    signature = f"{function_name}() {{"
    assert content.count(signature) == 1
    instrumented_signature = (
        f"{signature}\n"
        f"  printf 'instrument {function_name} %s\\n' \"${{1:-}}\" >> \"$MOCK_LOG\""
    )
    path.write_text(content.replace(signature, instrumented_signature, 1), encoding="utf-8")


def _application_dynamic_args() -> list[str]:
    return [
        "--set",
        "global.sharedStorage.mode=dynamic",
        "--set",
        "global.sharedStorage.storageClassName=rwx-storage",
        "--set",
        "nexent-supabase-db.persistence.mode=dynamic",
        "--set",
        "nexent-supabase-db.persistence.storageClassName=rwx-storage",
    ]


def _infrastructure_dynamic_args() -> list[str]:
    args: list[str] = []
    for component in sorted(INFRASTRUCTURE_DEPLOYMENTS):
        args.extend(
            [
                "--set",
                f"{component}.persistence.mode=dynamic",
                "--set",
                f"{component}.persistence.storageClassName=rwx-storage",
            ]
        )
    return args


def _application_existing_args() -> list[str]:
    return [
        "--set",
        "global.sharedStorage.mode=existing",
        "--set",
        "global.sharedStorage.workspace.existingClaim=prod-nexent-workspace",
        "--set",
        "global.sharedStorage.skills.existingClaim=prod-nexent-skills",
        "--set",
        "nexent-supabase-db.persistence.mode=existing",
        "--set",
        "nexent-supabase-db.persistence.existingClaim=prod-nexent-supabase-db",
    ]


def _infrastructure_existing_args() -> list[str]:
    args: list[str] = []
    for component in sorted(INFRASTRUCTURE_DEPLOYMENTS):
        args.extend(
            [
                "--set",
                f"{component}.persistence.mode=existing",
                "--set",
                f"{component}.persistence.existingClaim=prod-{component}",
            ]
        )
    return args


def _template(chart: Path, release: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["helm", "template", release, str(chart), *args], check=False)


def _documents(rendered: str) -> list[dict]:
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _resource_ids(documents: list[dict]) -> set[tuple[str, str, str, str]]:
    return {
        (
            document.get("apiVersion", ""),
            document.get("kind", ""),
            document.get("metadata", {}).get("namespace", ""),
            document.get("metadata", {}).get("name", ""),
        )
        for document in documents
    }


def _deploy_command(project: Path, scope: str = "all") -> list[str]:
    return [
        "bash",
        str(project / "deploy" / "k8s" / "deploy.sh"),
        "--defaults",
        "--release-scope",
        scope,
        "--components",
        "infrastructure,application",
        "--image-source",
        "local-latest",
        "--persistence-mode",
        "dynamic",
        "--storage-class",
        "rwx-storage",
        "--wait-timeout",
        "1",
    ]


def test_dynamic_and_existing_storage_lint_and_template(chart_dirs: dict[str, Path]) -> None:
    cases = (
        (chart_dirs["application"], "nexent", _application_dynamic_args()),
        (chart_dirs["application"], "nexent", _application_existing_args()),
        (chart_dirs["infrastructure"], "nexent-infrastructure", _infrastructure_dynamic_args()),
        (chart_dirs["infrastructure"], "nexent-infrastructure", _infrastructure_existing_args()),
    )
    for chart, release, args in cases:
        lint = _run(["helm", "lint", str(chart), *args], check=False)
        rendered = _template(chart, release, args)
        assert lint.returncode == 0, lint.stdout + lint.stderr
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr


def test_releases_have_disjoint_resource_ownership(chart_dirs: dict[str, Path]) -> None:
    application = _template(chart_dirs["application"], "nexent", _application_dynamic_args())
    infrastructure = _template(
        chart_dirs["infrastructure"],
        "nexent-infrastructure",
        _infrastructure_dynamic_args(),
    )
    assert application.returncode == 0, application.stderr
    assert infrastructure.returncode == 0, infrastructure.stderr

    application_documents = _documents(application.stdout)
    infrastructure_documents = _documents(infrastructure.stdout)
    assert not (_resource_ids(application_documents) & _resource_ids(infrastructure_documents))

    application_deployments = {
        item["metadata"]["name"]
        for item in application_documents
        if item.get("kind") == "Deployment"
    }
    infrastructure_deployments = {
        item["metadata"]["name"]
        for item in infrastructure_documents
        if item.get("kind") == "Deployment"
    }
    assert application_deployments == APPLICATION_DEPLOYMENTS
    assert infrastructure_deployments == INFRASTRUCTURE_DEPLOYMENTS


def test_elasticsearch_api_key_is_application_secret_only(
    chart_dirs: dict[str, Path],
) -> None:
    application = _template(
        chart_dirs["application"],
        "nexent",
        [
            *_application_dynamic_args(),
            "--set",
            "nexent-common.secrets.elasticsearchApiKey=test-api-key",
        ],
    )
    infrastructure = _template(
        chart_dirs["infrastructure"],
        "nexent-infrastructure",
        _infrastructure_dynamic_args(),
    )
    application_secrets = {
        item["metadata"]["name"]: item["data"]
        for item in _documents(application.stdout)
        if item.get("kind") == "Secret"
    }
    infrastructure_secrets = {
        item["metadata"]["name"]: item["data"]
        for item in _documents(infrastructure.stdout)
        if item.get("kind") == "Secret"
    }
    assert "ELASTICSEARCH_API_KEY" in application_secrets["nexent-secrets"]
    assert "ELASTIC_PASSWORD" not in application_secrets["nexent-secrets"]
    assert "ELASTICSEARCH_API_KEY" not in infrastructure_secrets[
        "nexent-infrastructure-secrets"
    ]
    assert "ELASTIC_PASSWORD" in infrastructure_secrets["nexent-infrastructure-secrets"]


def test_config_reads_official_skills_from_workspace_only(
    chart_dirs: dict[str, Path],
) -> None:
    rendered = _template(chart_dirs["application"], "nexent", _application_dynamic_args())
    assert rendered.returncode == 0, rendered.stderr

    documents = _documents(rendered.stdout)
    assert not any(
        document.get("kind") == "ConfigMap"
        and document["metadata"]["name"] == "nexent-official-skills"
        for document in documents
    )

    deployments = {
        document["metadata"]["name"]: document
        for document in documents
        if document.get("kind") == "Deployment"
    }
    for deployment_name, deployment in deployments.items():
        pod_spec = deployment["spec"]["template"]["spec"]
        mounts = {
            mount["name"]: mount
            for container in pod_spec["containers"]
            for mount in container.get("volumeMounts", [])
        }
        volumes = {volume["name"]: volume for volume in pod_spec.get("volumes", [])}
        assert "nexent-official-skills" not in mounts
        assert "nexent-official-skills" not in volumes
        if deployment_name == "nexent-config":
            assert mounts["nexent-workspace"]["mountPath"] == "/mnt/nexent"
            assert volumes["nexent-workspace"]["persistentVolumeClaim"]["claimName"] == (
                "nexent-workspace"
            )


def test_dynamic_storage_class_applies_to_release_owned_pvcs(
    chart_dirs: dict[str, Path],
) -> None:
    cases = (
        (chart_dirs["application"], "nexent", _application_dynamic_args(), APPLICATION_PVCS),
        (
            chart_dirs["infrastructure"],
            "nexent-infrastructure",
            _infrastructure_dynamic_args(),
            INFRASTRUCTURE_PVCS,
        ),
    )
    for chart, release, args, expected_claims in cases:
        rendered = _template(chart, release, args)
        claims = {
            document["metadata"]["name"]: document
            for document in _documents(rendered.stdout)
            if document.get("kind") == "PersistentVolumeClaim"
        }
        assert set(claims) == expected_claims
        assert all(
            claim["spec"]["storageClassName"] == "rwx-storage"
            for claim in claims.values()
        )


def test_nodeport_service_defaults_render_without_explicit_ports(chart_dirs: dict[str, Path]) -> None:
    application_args = [*_application_dynamic_args()]
    for component in (
        "nexent-config",
        "nexent-data-process",
        "nexent-mcp",
        "nexent-runtime",
        "nexent-supabase-auth",
        "nexent-supabase-db",
        "nexent-supabase-kong",
    ):
        application_args.extend(["--set", f"{component}.service.type=NodePort"])

    infrastructure_args = [*_infrastructure_dynamic_args()]
    for component in INFRASTRUCTURE_DEPLOYMENTS:
        infrastructure_args.extend(["--set", f"{component}.service.type=NodePort"])

    application = _template(chart_dirs["application"], "nexent", application_args)
    infrastructure = _template(
        chart_dirs["infrastructure"],
        "nexent-infrastructure",
        infrastructure_args,
    )

    assert application.returncode == 0, application.stderr
    assert infrastructure.returncode == 0, infrastructure.stderr


@pytest.mark.parametrize("component", sorted(INFRASTRUCTURE_DEPLOYMENTS))
def test_infrastructure_existing_storage_requires_each_claim(
    chart_dirs: dict[str, Path], component: str
) -> None:
    rendered = _template(
        chart_dirs["infrastructure"],
        "nexent-infrastructure",
        [*_infrastructure_existing_args(), "--set", f"{component}.persistence.existingClaim="],
    )
    assert rendered.returncode != 0
    assert f"{component}.persistence.existingClaim is required" in rendered.stderr


@pytest.mark.parametrize("component", sorted(INFRASTRUCTURE_DEPLOYMENTS))
def test_infrastructure_components_cannot_be_scaled(
    chart_dirs: dict[str, Path], component: str
) -> None:
    rendered = _template(
        chart_dirs["infrastructure"],
        "nexent-infrastructure",
        [*_infrastructure_dynamic_args(), "--set", f"{component}.replicaCount=2"],
    )
    assert rendered.returncode != 0
    assert f"{component} must remain single-replica" in rendered.stderr


def test_startup_recovery_deployments_use_single_replica_recreate(
    chart_dirs: dict[str, Path],
) -> None:
    rendered = _template(
        chart_dirs["application"],
        "nexent",
        _application_dynamic_args(),
    )
    assert rendered.returncode == 0, rendered.stderr

    deployments = {
        document["metadata"]["name"]: document
        for document in _documents(rendered.stdout)
        if document.get("kind") == "Deployment"
    }
    for component in STARTUP_RECOVERY_DEPLOYMENTS:
        spec = deployments[component]["spec"]
        assert spec["replicas"] == 1
        assert spec["strategy"] == {"type": "Recreate"}


@pytest.mark.parametrize("component", sorted(STARTUP_RECOVERY_DEPLOYMENTS))
def test_startup_recovery_deployments_cannot_be_scaled(
    chart_dirs: dict[str, Path],
    component: str,
) -> None:
    rendered = _template(
        chart_dirs["application"],
        "nexent",
        [*_application_dynamic_args(), "--set", f"{component}.replicaCount=2"],
    )
    assert rendered.returncode != 0
    assert f"{component} must remain single-replica" in rendered.stderr


@pytest.mark.parametrize("component", sorted(STARTUP_RECOVERY_DEPLOYMENTS))
def test_startup_recovery_deployments_require_recreate(
    chart_dirs: dict[str, Path],
    component: str,
) -> None:
    rendered = _template(
        chart_dirs["application"],
        "nexent",
        [
            *_application_dynamic_args(),
            "--set",
            f"{component}.strategy.type=RollingUpdate",
        ],
    )
    assert rendered.returncode != 0
    assert (
        f"{component} strategy.type must be Recreate"
        in rendered.stderr
    )


def test_stateless_web_can_still_be_scaled(chart_dirs: dict[str, Path]) -> None:
    rendered = _template(
        chart_dirs["application"],
        "nexent",
        [*_application_dynamic_args(), "--set", "nexent-web.replicaCount=2"],
    )
    assert rendered.returncode == 0, rendered.stderr
    web = next(
        document
        for document in _documents(rendered.stdout)
        if document.get("kind") == "Deployment"
        and document["metadata"]["name"] == "nexent-web"
    )
    assert web["spec"]["replicas"] == 2


def test_deploy_and_uninstall_scripts_have_valid_shell_syntax() -> None:
    for script in ("deploy.sh", "init-elasticsearch.sh", "uninstall.sh"):
        result = _run(
            ["bash", "-n", str(PROJECT_ROOT / "deploy" / "k8s" / script)],
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("component", "port"),
    (("nexent-config", 5010), ("nexent-runtime", 5014), ("nexent-northbound", 5013)),
)
def test_backend_charts_declare_delayed_process_health_probes(component: str, port: int) -> None:
    chart = APPLICATION_CHART_SOURCE / "charts" / component
    deployment = (chart / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    values = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))

    assert deployment.count("path: /health/live") == 2
    assert "path: /health/ready" in deployment
    assert f"port: {port}" in deployment
    assert "initialDelaySeconds: {{ .Values.probes.startup.initialDelaySeconds }}" in deployment
    assert values["probes"]["startup"] == {
        "initialDelaySeconds": 30,
        "periodSeconds": 5,
        "timeoutSeconds": 2,
        "failureThreshold": 60,
    }


def test_web_chart_declares_delayed_startup_probe() -> None:
    chart = APPLICATION_CHART_SOURCE / "charts" / "nexent-web"
    deployment = (chart / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    values = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))

    assert deployment.count("path: /") == 3
    assert "initialDelaySeconds: {{ .Values.probes.startup.initialDelaySeconds }}" in deployment
    assert values["probes"]["startup"] == {
        "initialDelaySeconds": 30,
        "periodSeconds": 5,
        "timeoutSeconds": 2,
        "failureThreshold": 60,
    }


def test_deploy_renders_generated_values_once_after_summary(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    common_script = project / "deploy" / "common" / "common.sh"
    deploy_script = project / "deploy" / "k8s" / "deploy.sh"
    for function_name in (
        "deployment_apply_image_source",
        "deployment_prepare_monitoring_env",
        "deployment_render_helm_values",
    ):
        _instrument_shell_function(common_script, function_name)
    for function_name in (
        "render_k8s_runtime_config_values",
        "render_infrastructure_runtime_values",
        "render_persistence_values",
    ):
        _instrument_shell_function(deploy_script, function_name)
    env["DEPLOYMENT_LANG"] = "en"

    result = _run(_deploy_command(project), check=False, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.index("Helm charts:") < result.stdout.index("Rendering generated image values")
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("instrument deployment_apply_image_source ") for line in commands) == 1
    assert sum(line.startswith("instrument deployment_prepare_monitoring_env ") for line in commands) == 1
    helm_value_renders = [
        line for line in commands if line.startswith("instrument deployment_render_helm_values ")
    ]
    assert len(helm_value_renders) == 2
    assert any(line.endswith("/helm/nexent/generated-values.yaml") for line in helm_value_renders)
    assert any(line.endswith("/helm/nexent-infrastructure/generated-values.yaml") for line in helm_value_renders)
    assert sum(line.startswith("instrument render_k8s_runtime_config_values ") for line in commands) == 1
    assert sum(line.startswith("instrument render_infrastructure_runtime_values ") for line in commands) == 1
    assert sum(line.startswith("instrument render_persistence_values ") for line in commands) == 1

    application_chart = project / "deploy" / "k8s" / "helm" / "nexent"
    infrastructure_chart = project / "deploy" / "k8s" / "helm" / "nexent-infrastructure"
    generated_values = (application_chart / "generated-values.yaml").read_text(encoding="utf-8")
    runtime_values = (application_chart / "generated-runtime-values.yaml").read_text(encoding="utf-8")
    persistence_values = (application_chart / "generated-persistence-values.yaml").read_text(encoding="utf-8")
    for output_name in (
        "generated-values.yaml",
        "generated-runtime-values.yaml",
        "generated-persistence-values.yaml",
    ):
        assert (infrastructure_chart / output_name).stat().st_size > 0
    assert 'imageSource: "local-latest"' in generated_values
    assert "sqlFileNames:" in runtime_values
    assert 'mode: "dynamic"' in persistence_values
    assert 'storageClassName: "rwx-storage"' in persistence_values


def test_invalid_persistence_mode_fails_before_render_or_config_persistence(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    command = _deploy_command(project)
    command[command.index("--persistence-mode") + 1] = "unsupported"

    result = _run(command, check=False, env=env)

    assert result.returncode != 0
    assert "Unsupported persistence mode: unsupported" in result.stdout
    assert "Rendering generated image values" not in result.stdout
    assert not (project / "deploy" / "k8s" / "deploy.options").exists()
    assert not mock_log.exists() or "helm " not in mock_log.read_text(encoding="utf-8")


def test_render_failure_does_not_persist_deploy_options_or_call_helm(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    (project / "deploy" / "sql" / "init.sql").unlink()

    result = _run(_deploy_command(project), check=False, env=env)

    assert result.returncode != 0
    assert "SQL init file not found" in result.stdout
    assert "Rendering generated image values" in result.stdout
    assert not (project / "deploy" / "k8s" / "deploy.options").exists()
    assert not mock_log.exists() or "helm " not in mock_log.read_text(encoding="utf-8")


def test_default_deploy_orders_releases_without_second_application_upgrade(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    result = _run(_deploy_command(project), check=False, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()

    infrastructure_helm = next(
        index
        for index, line in enumerate(commands)
        if line.startswith("helm upgrade --install nexent-infrastructure ")
    )
    readiness = [
        next(
            index
            for index, line in enumerate(commands)
            if f"rollout status deployment/{name}" in line
        )
        for name in (
            "nexent-elasticsearch",
            "nexent-postgresql",
            "nexent-redis",
            "nexent-minio",
        )
    ]
    es_initialization = next(
        index for index, line in enumerate(commands) if "_cluster/health" in line
    )
    application_helm = next(
        index
        for index, line in enumerate(commands)
        if line.startswith("helm upgrade --install nexent ")
    )
    application_readiness = [
        next(
            index
            for index, line in enumerate(commands)
            if f"rollout status deployment/{name}" in line
        )
        for name in (
            "nexent-config",
            "nexent-runtime",
            "nexent-mcp",
            "nexent-northbound",
            "nexent-web",
        )
    ]
    official_skills_copy = next(
        index for index, line in enumerate(commands) if line.startswith("kubectl cp ")
    )
    config_pod_lookup = next(
        line
        for line in commands
        if line.startswith("kubectl get pods ") and "app=nexent-config" in line
    )
    assert infrastructure_helm < min(readiness) <= max(readiness) < es_initialization
    assert es_initialization < application_helm
    assert application_helm < min(application_readiness) <= max(application_readiness)
    assert max(application_readiness) < official_skills_copy
    assert "--field-selector=status.phase=Running" in config_pod_lookup
    assert "--sort-by=.metadata.creationTimestamp" in config_pod_lookup
    assert sum(line.startswith("helm upgrade --install nexent ") for line in commands) == 1
    assert sum(line.startswith("kubectl cp ") for line in commands) == 1


def test_missing_official_skills_fails_before_helm(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    shutil.rmtree(project / "deploy" / "docker" / "assets" / "official-skills-zip")

    result = _run(_deploy_command(project), check=False, env=env)

    assert result.returncode != 0
    assert "official skills directory not found" in result.stdout
    assert not mock_log.exists() or "helm " not in mock_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("failure_env", "expected_error"),
    (
        ("MOCK_FAIL_OFFICIAL_COPY", "failed to copy official skills"),
        ("MOCK_FAIL_OFFICIAL_CHECKSUM", "failed SHA-256 verification"),
        ("MOCK_FAIL_OFFICIAL_PROMOTE", "previous version was preserved"),
    ),
)
def test_official_skills_sync_failure_is_retryable_without_second_helm(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
    failure_env: str,
    expected_error: str,
) -> None:
    project, env, mock_log = isolated_k8s_project
    _write_executable(
        project / "deploy" / "k8s" / "create-suadmin.sh",
        '#!/bin/bash\nprintf "suadmin\\n" >> "$MOCK_LOG"\n',
    )
    env["MOCK_INFRA_EXISTS"] = "true"
    env[failure_env] = "true"
    command = _deploy_command(project, "nexent")
    command[command.index("--components") + 1] = "application,supabase"

    failed = _run(command, check=False, env=env)

    assert failed.returncode != 0
    assert expected_error in failed.stdout
    assert "Super Admin User Creation" not in failed.stdout
    failed_commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("helm upgrade --install nexent ") for line in failed_commands) == 1
    assert "suadmin" not in failed_commands

    mock_log.write_text("", encoding="utf-8")
    env[failure_env] = "false"
    retried = _run(command, check=False, env=env)

    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert "Official skills synchronized" in retried.stdout
    assert retried.stdout.index("Official skills synchronized") < retried.stdout.index(
        "Super Admin User Creation"
    )
    retry_commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("helm upgrade --install nexent ") for line in retry_commands) == 1
    assert sum(line.startswith("kubectl cp ") for line in retry_commands) == 1
    assert retry_commands.count("suadmin") == 1
    official_skills_copy = next(
        index for index, line in enumerate(retry_commands) if line.startswith("kubectl cp ")
    )
    assert official_skills_copy < retry_commands.index("suadmin")


def test_deploy_without_application_component_skips_official_skills_sync(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    env["MOCK_INFRA_EXISTS"] = "true"
    command = _deploy_command(project, "nexent")
    command[command.index("--components") + 1] = "data-process"

    result = _run(command, check=False, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "kubectl cp " not in mock_log.read_text(encoding="utf-8")


@pytest.mark.parametrize("persistence_mode", ["local", "dynamic", "existing"])
def test_official_skills_sync_is_storage_mode_independent(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
    persistence_mode: str,
) -> None:
    project, env, mock_log = isolated_k8s_project
    env["MOCK_INFRA_EXISTS"] = "true"
    command = _deploy_command(project, "nexent")
    command[command.index("--persistence-mode") + 1] = persistence_mode
    storage_option_index = command.index("--storage-class")
    if persistence_mode == "local":
        del command[storage_option_index:storage_option_index + 2]
    elif persistence_mode == "existing":
        command[storage_option_index:storage_option_index + 2] = [
            "--existing-claim-prefix",
            "prod",
        ]

    result = _run(command, check=False, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("kubectl cp ") for line in commands) == 1


@pytest.mark.parametrize(
    ("failure_env", "expected_error"),
    [
        ({"MOCK_FAIL_ROLLOUT": "nexent-postgresql"}, "Infrastructure is not ready"),
        ({"MOCK_FAIL_ES_INIT": "true"}, "API key initialization failed"),
    ],
)
def test_infrastructure_or_es_failure_prevents_application_release(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
    failure_env: dict[str, str],
    expected_error: str,
) -> None:
    project, env, mock_log = isolated_k8s_project
    env.update(failure_env)
    result = _run(_deploy_command(project), check=False, env=env)
    assert result.returncode != 0
    assert expected_error in result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8")
    assert "helm upgrade --install nexent " not in commands


def test_nexent_scope_requires_infrastructure_release(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    result = _run(_deploy_command(project, "nexent"), check=False, env=env)
    assert result.returncode != 0
    assert "infrastructure release 'nexent-infrastructure' does not exist" in result.stdout
    assert "helm upgrade --install" not in mock_log.read_text(encoding="utf-8")


def test_legacy_single_release_is_rejected_before_helm_upgrade(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    env.update({"MOCK_APP_EXISTS": "true", "MOCK_LEGACY_RELEASE": "true"})
    result = _run(_deploy_command(project), check=False, env=env)
    assert result.returncode != 0
    assert "Automatic migration from the legacy single release is not supported" in result.stdout
    assert "helm upgrade --install" not in mock_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("scope", "infra_exists", "expected_infra_upgrades", "expected_app_upgrades"),
    [
        ("infrastructure", "false", 1, 0),
        ("nexent", "true", 0, 1),
        ("all", "false", 1, 1),
    ],
)
def test_deploy_release_scopes(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
    scope: str,
    infra_exists: str,
    expected_infra_upgrades: int,
    expected_app_upgrades: int,
) -> None:
    project, env, mock_log = isolated_k8s_project
    env["MOCK_INFRA_EXISTS"] = infra_exists
    result = _run(_deploy_command(project, scope), check=False, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    assert sum(
        line.startswith("helm upgrade --install nexent-infrastructure ") for line in commands
    ) == expected_infra_upgrades
    assert sum(line.startswith("helm upgrade --install nexent ") for line in commands) == expected_app_upgrades
    assert sum(line.startswith("kubectl cp ") for line in commands) == expected_app_upgrades


def test_uninstall_default_order_and_scopes(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    uninstall = project / "deploy" / "k8s" / "uninstall.sh"
    result = _run(
        ["bash", str(uninstall), "--keep-namespace", "--keep-local-data"],
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8").splitlines()
    app_index = commands.index("helm uninstall nexent --namespace nexent")
    infra_index = commands.index("helm uninstall nexent-infrastructure --namespace nexent")
    assert app_index < infra_index


def test_uninstall_nexent_scope_leaves_infrastructure_release(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    result = _run(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--release-scope",
            "nexent",
            "--keep-namespace",
            "--keep-local-data",
        ],
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = mock_log.read_text(encoding="utf-8")
    assert "helm uninstall nexent --namespace nexent" in commands
    assert "helm uninstall nexent-infrastructure" not in commands


def test_uninstall_infrastructure_scope_has_dependency_guard(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, mock_log = isolated_k8s_project
    env["MOCK_APP_EXISTS"] = "true"
    result = _run(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--release-scope",
            "infrastructure",
            "--keep-namespace",
            "--keep-local-data",
        ],
        check=False,
        env=env,
    )
    assert result.returncode != 0
    assert "cannot uninstall 'nexent-infrastructure'" in result.stdout
    assert "helm uninstall" not in mock_log.read_text(encoding="utf-8")


@pytest.mark.parametrize("persistence_mode", ["dynamic", "existing"])
def test_uninstall_non_local_mode_skips_local_data_prompt_in_tty(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
    persistence_mode: str,
) -> None:
    project, env, _ = isolated_k8s_project
    (project / "deploy" / "k8s" / "deploy.options").write_text(
        f'k8s:\n  persistenceMode: "{persistence_mode}"\n',
        encoding="utf-8",
    )
    env["DEPLOYMENT_LANG"] = "en"

    result = _run_in_pseudo_tty(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--keep-namespace",
        ],
        env=env,
        input_text="n\n",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Persistence mode is '{persistence_mode}'; skipping local PV directory cleanup." in result.stdout
    assert "Delete local PV data under" not in result.stdout
    assert "Deleting local PV data" not in result.stdout


@pytest.mark.parametrize("persistence_mode", ["dynamic", "existing"])
@pytest.mark.parametrize(
    "arguments",
    [
        ["--delete-local-data", "true", "--keep-namespace"],
        ["delete-all", "--keep-namespace"],
    ],
    ids=["explicit-delete", "delete-all"],
)
def test_uninstall_non_local_mode_ignores_local_data_deletion(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
    persistence_mode: str,
    arguments: list[str],
) -> None:
    project, env, _ = isolated_k8s_project
    (project / "deploy" / "k8s" / "deploy.options").write_text(
        f"k8s:\n  persistenceMode: {persistence_mode}\n",
        encoding="utf-8",
    )
    env["DEPLOYMENT_LANG"] = "en"

    result = _run(
        ["bash", str(project / "deploy" / "k8s" / "uninstall.sh"), *arguments],
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Persistence mode is '{persistence_mode}'; skipping local PV directory cleanup." in result.stdout
    assert "Deleting local PV data" not in result.stdout


def test_uninstall_reads_legacy_persistence_mode(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _ = isolated_k8s_project
    (project / "deploy" / "k8s" / "deploy.options").write_text(
        "PERSISTENCE_MODE='dynamic'\n",
        encoding="utf-8",
    )
    env["DEPLOYMENT_LANG"] = "en"

    result = _run(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--delete-local-data",
            "true",
            "--keep-namespace",
        ],
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Persistence mode is 'dynamic'; skipping local PV directory cleanup." in result.stdout
    assert "Deleting local PV data" not in result.stdout


def test_uninstall_non_local_mode_still_validates_local_data_option(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _ = isolated_k8s_project
    (project / "deploy" / "k8s" / "deploy.options").write_text(
        "k8s:\n  persistenceMode: dynamic\n",
        encoding="utf-8",
    )
    env["DEPLOYMENT_LANG"] = "en"

    result = _run(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--delete-local-data",
            "invalid",
            "--keep-namespace",
        ],
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "Invalid boolean value: invalid." in result.stdout


def test_uninstall_local_mode_keeps_prompt_and_explicit_options(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _ = isolated_k8s_project
    (project / "deploy" / "k8s" / "deploy.options").write_text(
        "k8s:\n  persistenceMode: local\n",
        encoding="utf-8",
    )
    env["DEPLOYMENT_LANG"] = "en"

    prompted = _run_in_pseudo_tty(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--keep-namespace",
        ],
        env=env,
        input_text="n\n",
    )
    kept = _run(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--keep-local-data",
            "--keep-namespace",
        ],
        check=False,
        env=env,
    )

    safe_bin = project / "safe-bin"
    safe_bin.mkdir()
    _write_executable(safe_bin / "rm", "#!/bin/bash\nexit 0\n")
    delete_env = env.copy()
    delete_env["PATH"] = f"{safe_bin}:{delete_env['PATH']}"
    deleted = _run(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--delete-local-data",
            "true",
            "--keep-namespace",
        ],
        check=False,
        env=delete_env,
    )

    assert prompted.returncode == 0, prompted.stdout + prompted.stderr
    assert "Delete local PV data under" in prompted.stdout
    assert "Local PV data preserved." in prompted.stdout
    assert kept.returncode == 0, kept.stdout + kept.stderr
    assert "Local PV data preserved." in kept.stdout
    assert deleted.returncode == 0, deleted.stdout + deleted.stderr
    assert "Deleting local PV data..." in deleted.stdout


@pytest.mark.parametrize(
    "deploy_options",
    [
        None,
        "not: [valid\n",
        "k8s:\n  persistenceMode: unsupported\n",
    ],
    ids=["missing", "damaged", "unknown"],
)
def test_uninstall_unknown_persistence_mode_keeps_compatible_prompt(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
    deploy_options: str | None,
) -> None:
    project, env, _ = isolated_k8s_project
    if deploy_options is not None:
        (project / "deploy" / "k8s" / "deploy.options").write_text(deploy_options, encoding="utf-8")
    env["DEPLOYMENT_LANG"] = "en"

    result = _run_in_pseudo_tty(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--keep-namespace",
        ],
        env=env,
        input_text="n\n",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Delete local PV data under" in result.stdout
    assert "Local PV data preserved." in result.stdout


def test_uninstall_missing_persistence_mode_non_interactive_preserves_local_data(
    isolated_k8s_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _ = isolated_k8s_project
    env["DEPLOYMENT_LANG"] = "en"

    result = _run(
        [
            "bash",
            str(project / "deploy" / "k8s" / "uninstall.sh"),
            "--keep-namespace",
        ],
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Delete local PV data under" not in result.stdout
    assert "Local PV data preserved." in result.stdout
