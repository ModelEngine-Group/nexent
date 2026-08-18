import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHART_SOURCE = PROJECT_ROOT / "deploy" / "k8s" / "helm" / "nexent"
WEB_DOCKERFILE = PROJECT_ROOT / "deploy" / "images" / "dockerfiles" / "web" / "Dockerfile"
APPLICATIONS = {
    "nexent-web": {"/mnt/nexent"},
    "nexent-config": {"/mnt/nexent", "/mnt/nexent-data/skills"},
    "nexent-runtime": {"/mnt/nexent", "/mnt/nexent-data/skills"},
    "nexent-northbound": {"/mnt/nexent", "/mnt/nexent-data/skills"},
}
SINGLE_REPLICA_COMPONENTS = {
    "nexent-mcp",
    "nexent-data-process",
    "nexent-elasticsearch",
    "nexent-postgresql",
    "nexent-redis",
    "nexent-minio",
    "nexent-supabase-kong",
    "nexent-supabase-auth",
    "nexent-supabase-db",
}
MANAGED_PVCS = {
    "nexent-workspace",
    "nexent-skills",
    "nexent-elasticsearch",
    "nexent-postgresql",
    "nexent-redis",
    "nexent-minio",
    "nexent-supabase-db",
}


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture(scope="module")
def chart_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("helm") is None:
        pytest.skip("helm is required for Kubernetes chart tests")

    destination = tmp_path_factory.mktemp("nexent-helm") / "nexent"
    shutil.copytree(CHART_SOURCE, destination)
    _run(["helm", "dependency", "update", str(destination)])
    return destination


@pytest.fixture(scope="module")
def isolated_deploy_script(tmp_path_factory: pytest.TempPathFactory) -> Path:
    project = tmp_path_factory.mktemp("nexent-deploy")
    shutil.copytree(PROJECT_ROOT / "deploy", project / "deploy")
    const_dir = project / "backend" / "consts"
    const_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "backend" / "consts" / "const.py", const_dir / "const.py")
    return project / "deploy" / "k8s" / "deploy.sh"


def _dynamic_args() -> list[str]:
    return ["--set", "global.sharedStorage.storageClassName=rwx-storage"]


def _existing_args() -> list[str]:
    args = [
        "--set",
        "global.sharedStorage.mode=existing",
        "--set",
        "global.sharedStorage.workspace.existingClaim=prod-nexent-workspace",
        "--set",
        "global.sharedStorage.skills.existingClaim=prod-nexent-skills",
    ]
    for component in (
        "nexent-elasticsearch",
        "nexent-postgresql",
        "nexent-redis",
        "nexent-minio",
        "nexent-supabase-db",
    ):
        args.extend(
            [
                "--set",
                f"{component}.persistence.mode=existing",
                "--set",
                f"{component}.persistence.existingClaim=prod-{component}",
            ]
        )
    return args


def _template(chart_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["helm", "template", "nexent", str(chart_dir), *args], check=False)


def _documents(rendered: str) -> list[dict]:
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def test_dynamic_and_existing_storage_lint_and_template(chart_dir: Path) -> None:
    for args in (_dynamic_args(), _existing_args()):
        lint = _run(["helm", "lint", str(chart_dir), *args], check=False)
        rendered = _template(chart_dir, args)
        assert lint.returncode == 0, lint.stdout + lint.stderr
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr


def test_dynamic_storage_class_applies_to_all_managed_pvcs(chart_dir: Path) -> None:
    rendered = _template(chart_dir, _dynamic_args())
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr

    claims = {
        document["metadata"]["name"]: document
        for document in _documents(rendered.stdout)
        if document.get("kind") == "PersistentVolumeClaim"
        and document.get("metadata", {}).get("name") in MANAGED_PVCS
    }

    assert set(claims) == MANAGED_PVCS
    assert all(claim["spec"]["storageClassName"] == "rwx-storage" for claim in claims.values())


def test_three_replica_workloads_render_rollout_and_health_contract(chart_dir: Path) -> None:
    rendered = _template(chart_dir, _dynamic_args())
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    documents = _documents(rendered.stdout)
    deployments = {
        document["metadata"]["name"]: document
        for document in documents
        if document.get("kind") == "Deployment"
    }
    pdbs = {
        document["metadata"]["name"]: document
        for document in documents
        if document.get("kind") == "PodDisruptionBudget"
    }

    for name, expected_mounts in APPLICATIONS.items():
        deployment = deployments[name]
        assert deployment["spec"]["replicas"] == 3
        assert deployment["spec"]["strategy"] == {
            "type": "RollingUpdate",
            "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
        }

        pod_spec = deployment["spec"]["template"]["spec"]
        assert "terminationGracePeriodSeconds" not in pod_spec
        preferred = pod_spec["affinity"]["podAntiAffinity"][
            "preferredDuringSchedulingIgnoredDuringExecution"
        ]
        assert preferred[0]["podAffinityTerm"]["labelSelector"]["matchLabels"] == {"app": name}
        assert preferred[0]["podAffinityTerm"]["topologyKey"] == "kubernetes.io/hostname"

        container = pod_spec["containers"][0]
        assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
        assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
        assert "lifecycle" not in container
        mounts = {mount["mountPath"] for mount in container.get("volumeMounts", [])}
        assert expected_mounts <= mounts

        assert pdbs[name]["spec"]["minAvailable"] == 1
        assert pdbs[name]["spec"]["selector"]["matchLabels"] == {"app": name}

    for name in SINGLE_REPLICA_COMPONENTS:
        assert deployments[name]["spec"]["replicas"] == 1


@pytest.mark.parametrize(
    ("args", "expected_error"),
    [
        ([], "storageClassName is required"),
        (
            ["--set", "global.sharedStorage.mode=local"],
            "mode=local is not supported",
        ),
        (
            [
                "--set",
                "global.sharedStorage.storageClassName=rwx-storage",
                "--set",
                "global.sharedStorage.accessModes[0]=ReadWriteOnce",
            ],
            "require ReadWriteMany",
        ),
        (
            [
                "--set",
                "global.sharedStorage.mode=existing",
                "--set",
                "global.sharedStorage.skills.existingClaim=prod-nexent-skills",
            ],
            "workspace.existingClaim is required",
        ),
        (
            [
                "--set",
                "global.sharedStorage.mode=existing",
                "--set",
                "global.sharedStorage.workspace.existingClaim=prod-nexent-workspace",
            ],
            "skills.existingClaim is required",
        ),
        (
            [
                "--set",
                "global.sharedStorage.mode=existing",
                "--set",
                "global.sharedStorage.workspace.existingClaim=prod-nexent-workspace",
                "--set",
                "global.sharedStorage.skills.existingClaim=prod-nexent-skills",
            ],
            "nexent-elasticsearch.persistence.mode must be existing",
        ),
    ],
)
def test_invalid_shared_storage_is_rejected(
    chart_dir: Path,
    args: list[str],
    expected_error: str,
) -> None:
    rendered = _template(chart_dir, args)
    assert rendered.returncode != 0
    assert expected_error in rendered.stderr


@pytest.mark.parametrize(
    "component",
    [
        "nexent-elasticsearch",
        "nexent-postgresql",
        "nexent-redis",
        "nexent-minio",
        "nexent-supabase-db",
    ],
)
def test_existing_stateful_storage_requires_every_claim(chart_dir: Path, component: str) -> None:
    rendered = _template(
        chart_dir,
        [*_existing_args(), "--set", f"{component}.persistence.existingClaim="],
    )

    assert rendered.returncode != 0
    assert f"{component}.persistence.existingClaim is required" in rendered.stderr


@pytest.mark.parametrize("component", sorted(SINGLE_REPLICA_COMPONENTS))
def test_single_replica_components_cannot_be_scaled(chart_dir: Path, component: str) -> None:
    rendered = _template(
        chart_dir,
        [*_dynamic_args(), "--set", f"{component}.replicaCount=2"],
    )
    assert rendered.returncode != 0
    assert f"{component} must remain single-replica" in rendered.stderr


def test_deploy_script_has_valid_shell_syntax(isolated_deploy_script: Path) -> None:
    result = _run(["bash", "-n", str(isolated_deploy_script)], check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_web_image_packages_process_health_module() -> None:
    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")

    assert "cp server-health.js ../frontend-dist/server-health.js" in dockerfile


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        (
            ["--persistence-mode", "local"],
            "local/hostPath persistence is incompatible",
        ),
        (
            ["--persistence-mode", "dynamic"],
            "--storage-class is required",
        ),
        (
            ["--persistence-mode", "existing"],
            "--existing-claim-prefix is required",
        ),
    ],
)
def test_deploy_defaults_reject_unsafe_storage_options(
    isolated_deploy_script: Path,
    arguments: list[str],
    expected_error: str,
) -> None:
    result = _run(
        ["bash", str(isolated_deploy_script), "--defaults", *arguments],
        check=False,
    )
    assert result.returncode != 0
    assert expected_error in result.stdout + result.stderr
