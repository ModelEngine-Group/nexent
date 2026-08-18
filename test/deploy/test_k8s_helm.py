import os
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
    "nexent-config": {"/mnt/nexent", "/mnt/nexent-data/skills"},
    "nexent-runtime": {"/mnt/nexent", "/mnt/nexent-data/skills"},
    "nexent-northbound": {"/mnt/nexent", "/mnt/nexent-data/skills"},
}
APPLICATION_SINGLE_REPLICA = {
    "nexent-mcp",
    "nexent-data-process",
    "nexent-supabase-kong",
    "nexent-supabase-auth",
    "nexent-supabase-db",
}
APPLICATION_PVCS = {"nexent-workspace", "nexent-skills", "nexent-supabase-db"}
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
if [ "$1" = "get" ] && [ "$2" = "secret" ]; then
  case "$*" in
    *nexent-infrastructure-secrets*ELASTIC_PASSWORD*) printf 'bmV4ZW50QDIwMjU='; exit 0 ;;
  esac
  exit 1
fi
if [ "$1" = "rollout" ]; then
  case "$*" in
    *"${MOCK_FAIL_ROLLOUT:-__none__}"*) exit 1 ;;
  esac
  exit 0
fi
if [ "$1" = "exec" ]; then
  case "$*" in
    *_cluster/health*) printf '{"status":"yellow"}'; exit 0 ;;
    *_security/api_key*)
      if [ "${MOCK_FAIL_ES_INIT:-false}" = "true" ]; then printf '{"error":"failed"}'; else printf '{"encoded":"test-api-key"}'; fi
      exit 0
      ;;
    *_security/_authenticate*) printf '200'; exit 0 ;;
  esac
fi
exit 0
""",
    )
    _write_executable(mock_bin / "docker", "#!/bin/bash\nexit 0\n")

    env = os.environ.copy()
    env.pop("ELASTICSEARCH_API_KEY", None)
    env["PATH"] = f"{mock_bin}:{env['PATH']}"
    env["MOCK_LOG"] = str(mock_log)
    env["NEXENT_SYNC_ES_KEY_TO_ENV"] = "false"
    return project, env, mock_log


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _application_dynamic_args() -> list[str]:
    return ["--set", "global.sharedStorage.storageClassName=rwx-storage"]


def _infrastructure_dynamic_args() -> list[str]:
    args: list[str] = []
    for component in sorted(INFRASTRUCTURE_DEPLOYMENTS):
        args.extend(["--set", f"{component}.persistence.storageClassName=rwx-storage"])
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


def test_deploy_and_uninstall_scripts_have_valid_shell_syntax() -> None:
    for script in ("deploy.sh", "init-elasticsearch.sh", "uninstall.sh"):
        result = _run(
            ["bash", "-n", str(PROJECT_ROOT / "deploy" / "k8s" / script)],
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


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
    assert infrastructure_helm < min(readiness) <= max(readiness) < es_initialization
    assert es_initialization < application_helm
    assert sum(line.startswith("helm upgrade --install nexent ") for line in commands) == 1


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

