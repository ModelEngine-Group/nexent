# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check PVC retention and targeted removal through the uninstall entry point."""

import os
import select
import shutil
import subprocess

import pytest

from .test_workbench_publication import BASH, REPO


@pytest.fixture
def uninstall(tmp_path, monkeypatch):
    root = tmp_path / "project"
    script = root / "deploy/k8s/uninstall.sh"
    script.parent.mkdir(parents=True)
    common = root / "deploy/common"
    common.mkdir()
    shutil.copyfile(REPO / "deploy/k8s/uninstall.sh", script)
    shutil.copyfile(REPO / "deploy/common/common.sh", common / "common.sh")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    claims = tmp_path / "claims"
    calls = tmp_path / "calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("DEPLOYMENT_LANG", "en")
    monkeypatch.setenv("FIXTURE_MANIFESTS", manifests.as_posix())
    monkeypatch.setenv("FIXTURE_CLAIMS", claims.as_posix())
    monkeypatch.setenv("FIXTURE_CALLS", calls.as_posix())
    for binary, code in {
        "helm": r'''
printf 'helm %s\n' "$*" >> "$FIXTURE_CALLS"
case "$1:$2" in
  get:manifest) [ -f "$FIXTURE_MANIFESTS/$3" ] && cat "$FIXTURE_MANIFESTS/$3" || { echo 'Error: release: not found' >&2; exit 1; } ;;
  status:*) [ -f "$FIXTURE_MANIFESTS/$2" ] ;;
  uninstall:*)
    if [ "${FIXTURE_UNINSTALL_ERROR_RELEASE:-}" = "$2" ]; then
      printf 'Error: %s\n' "$FIXTURE_UNINSTALL_ERROR" >&2
      exit 1
    fi
    if [ ! -f "$FIXTURE_MANIFESTS/$2" ]; then
      echo 'Error: release: not found' >&2
      exit 1
    fi
    echo 'Warning: Helm uninstall fixture warning' >&2
    echo 'These resources were kept due to the resource policy:'
    echo '[PersistentVolumeClaim] fixture-claim'
    ;;
  *) exit 9 ;;
esac
''',
        "kubectl": r'''
printf 'kubectl %s\n' "$*" >> "$FIXTURE_CALLS"
case "$1:$2" in
  get:pvc) cat "$FIXTURE_CLAIMS" ;;
  get:namespace) echo 'namespace/test-ns' ;;
  delete:--raw)
    cat >> "$FIXTURE_CALLS"
    [ "${FIXTURE_PVC_MISSING:-0}" = 0 ] || { echo 'Error from server (NotFound): the claim is absent' >&2; exit 1; }
    [ "${FIXTURE_UID_CONFLICT:-0}" = 0 ] || { echo 'Error from server (Conflict): the UID was replaced' >&2; exit 1; }
    ;;
  delete:*) ;;
  *) exit 9 ;;
esac
''',
    }.items():
        mock = bin_dir / binary
        mock.write_text(f"#!/usr/bin/env bash\n{code}", encoding="utf-8")
        mock.chmod(0o700)

    def run(*arguments, legacy=False, released=False, answer=None, ssh_keys=False):
        claims.write_text(
            f"nexent-workspace|uid-workspace|nexent|test-ns|{'dynamic' if not legacy else ''}\n"
            "nexent-redis|uid-redis|nexent-infrastructure|test-ns|dynamic\n"
            "nexent-skills|uid-local|nexent|test-ns|\n"
            "other|uid-other|other-release|test-ns|dynamic\n"
            "wrong-namespace|uid-wrong|nexent|other-ns|dynamic\n"
            + ("nexent-ssh-keys|uid-ssh-keys|nexent|test-ns|dynamic\n" if ssh_keys else ""),
            encoding="utf-8",
        )
        if not released:
            (manifests / "nexent").write_text(
                "---\nkind: PersistentVolumeClaim\nmetadata:\n  name: nexent-workspace\n"
                + ("" if legacy else '  annotations:\n    helm.sh/resource-policy: "keep"\n')
                + "spec:\n  accessModes: []\n---\nkind: PersistentVolumeClaim\nmetadata:\n  name: nexent-skills\n"
                "spec:\n  volumeName: nexent-skills-pv\n"
                + ("---\nkind: PersistentVolumeClaim\nmetadata:\n  name: nexent-ssh-keys\n"
                   "  annotations:\n    helm.sh/resource-policy: keep\nspec:\n  accessModes: []\n" if ssh_keys else ""),
                encoding="utf-8",
            )
            (manifests / "nexent-infrastructure").write_text(
                "---\nkind: PersistentVolumeClaim\nmetadata:\n  name: nexent-redis\n"
                "  annotations:\n    helm.sh/resource-policy: keep\nspec:\n  accessModes: []\n",
                encoding="utf-8",
            )
        command = [BASH, script.as_posix(), "--namespace", "test-ns", "--keep-local-data", *arguments]
        if answer is None:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    check=False, timeout=20)
        else:
            import pty

            master, slave = pty.openpty()
            with subprocess.Popen(command, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) as process:
                os.close(slave)
                try:
                    ready, _, _ = select.select([process.stderr], [], [], 10)
                    assert ready, "The PVC prompt was not shown"
                    prompt = os.read(process.stderr.fileno(), 4096).decode()
                    assert "Delete dynamic PVCs" in prompt and "[y/N]" in prompt
                    os.write(master, f"{answer}\n".encode())
                    output, error = process.communicate(timeout=20)
                    result = subprocess.CompletedProcess(command, process.returncode, output, prompt + error)
                finally:
                    if process.poll() is None:
                        process.kill()
                    os.close(master)
        return result, calls.read_text(encoding="utf-8")

    return run


@pytest.mark.parametrize("arguments", [(), ("delete-all",), ("--delete-pvc", "false", "--remove-namespace")])
def test_preserving_claims_also_preserves_the_namespace(uninstall, arguments):
    result, calls = uninstall(*arguments)
    assert result.returncode == 0, result.stderr
    assert "Preserved dynamic PVCs: nexent-workspace nexent-redis" in result.stdout
    assert "These resources were kept due to the resource policy:" in result.stdout
    assert "helm uninstall nexent --namespace test-ns" in calls
    assert "helm uninstall nexent-infrastructure --namespace test-ns" in calls
    assert "kubectl delete --raw" not in calls
    assert "kubectl delete namespace" not in calls


@pytest.mark.skipif(os.name != "posix", reason="The fixture requires a POSIX pseudo-terminal")
@pytest.mark.parametrize("answer,deleted", [
    ("", False), (" ", False), ("n", False), ("yes", False), ("Y", False), (" y ", False), ("y", True),
])
def test_prompt_only_deletes_for_literal_lowercase_y(uninstall, answer, deleted):
    result, calls = uninstall("--remove-namespace", answer=answer)
    assert result.returncode == 0, result.stderr
    assert ("kubectl delete --raw" in calls) == deleted
    assert ("kubectl delete namespace" in calls) == deleted
    assert ("Deleting dynamic PVCs..." in result.stdout) == deleted
    if deleted:
        application_uninstall = calls.index("helm uninstall nexent --namespace test-ns")
        infrastructure_uninstall = calls.index("helm uninstall nexent-infrastructure --namespace test-ns")
        leftover_cleanup_start = calls.index("kubectl delete deployment nexent-data-process")
        leftover_cleanup_end = calls.index("kubectl delete deployment,service,configmap,rs,pod "
                                           "-n test-ns -l app=nexent-langfuse-worker")
        first_pvc_delete = calls.index("kubectl delete --raw")
        assert application_uninstall < infrastructure_uninstall < leftover_cleanup_start
        assert leftover_cleanup_start < leftover_cleanup_end < first_pvc_delete
        assert '"preconditions":{"uid":"uid-redis"}' in calls
        helm_stage = result.stdout.index("Uninstalling Helm release...")
        leftover_cleanup_log = result.stdout.index("Cleaning up leftover monitoring resources...")
        pvc_stage = result.stdout.index("Deleting dynamic PVCs...")
        assert helm_stage < leftover_cleanup_log < pvc_stage
        assert "These resources were kept due to the resource policy:" not in result.stdout + result.stderr
        assert "Warning: Helm uninstall fixture warning" in result.stderr


@pytest.mark.parametrize("released", [False, True])
def test_explicit_delete_is_scoped_and_uses_the_discovered_uid(uninstall, released):
    result, calls = uninstall("--release-scope", "nexent", "--delete-pvc", "true", released=released)
    assert result.returncode == 0, result.stderr
    helm_uninstall = calls.index("helm uninstall nexent --namespace test-ns")
    leftover_cleanup = calls.index("kubectl delete deployment nexent-data-process")
    assert helm_uninstall < leftover_cleanup < calls.index("kubectl delete --raw")
    deletions = [call for call in calls.splitlines() if call.startswith("kubectl delete --raw")]
    assert deletions == ["kubectl delete --raw /api/v1/namespaces/test-ns/persistentvolumeclaims/nexent-workspace -f -"]
    assert '"preconditions":{"uid":"uid-workspace"}' in calls
    assert "helm uninstall nexent-infrastructure" not in calls
    if released:
        assert "Helm release 'nexent' is already absent" in result.stdout


@pytest.mark.parametrize("delete", ["false", "true"])
def test_shared_ssh_claim_follows_dynamic_pvc_retention(uninstall, delete):
    result, calls = uninstall("--release-scope", "nexent", "--delete-pvc", delete, ssh_keys=True)
    assert result.returncode == 0, result.stderr
    if delete == "true":
        assert "persistentvolumeclaims/nexent-ssh-keys -f -" in calls
        assert '"preconditions":{"uid":"uid-ssh-keys"}' in calls
    else:
        assert "Preserved dynamic PVCs: nexent-workspace nexent-ssh-keys" in result.stdout
        assert "kubectl delete --raw" not in calls


def test_legacy_dynamic_claims_without_keep_policy_stop_before_helm_uninstall(uninstall):
    result, calls = uninstall(legacy=True)
    assert result.returncode != 0
    assert "nexent/nexent-workspace" in result.stderr
    assert "helm uninstall" not in calls
    assert "kubectl delete" not in calls


def test_explicit_legacy_removal_accepts_claims_already_deleted_by_helm(uninstall, monkeypatch):
    monkeypatch.setenv("FIXTURE_PVC_MISSING", "1")
    result, calls = uninstall("--release-scope", "nexent", "--delete-pvc", "true", legacy=True)
    assert result.returncode == 0, result.stderr
    assert "helm uninstall nexent --namespace test-ns" in calls
    assert "persistentvolumeclaims/nexent-workspace" in calls


@pytest.mark.parametrize("release,error", [
    ("nexent", "unable to uninstall release nexent"),
    ("nexent-infrastructure", "unable to uninstall release nexent-infrastructure"),
    ("nexent", "a service not found"),
    ("nexent", 'release "another-release" not found'),
])
def test_failed_helm_uninstall_leaves_pvcs_and_namespace_alone(uninstall, monkeypatch, release, error):
    monkeypatch.setenv("FIXTURE_UNINSTALL_ERROR_RELEASE", release)
    monkeypatch.setenv("FIXTURE_UNINSTALL_ERROR", error)
    result, calls = uninstall("--delete-pvc", "true", "--remove-namespace")
    assert result.returncode != 0
    assert f"Error: {error}" in result.stderr
    assert "Deleting dynamic PVCs..." not in result.stdout
    assert "kubectl delete --raw" not in calls
    assert "kubectl delete namespace" not in calls


def test_replaced_pvc_prevents_namespace_deletion(uninstall, monkeypatch):
    monkeypatch.setenv("FIXTURE_UID_CONFLICT", "1")
    result, calls = uninstall("--delete-pvc", "true", "--remove-namespace")
    assert result.returncode != 0
    assert "the UID was replaced" in result.stderr
    assert calls.index("kubectl delete deployment nexent-data-process") < calls.index("kubectl delete --raw")
    assert "kubectl delete namespace" not in calls
