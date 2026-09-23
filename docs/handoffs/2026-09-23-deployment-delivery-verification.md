# Deployment delivery verification — 2026-09-23

Implementation baseline: `develop` at `473b65268`. The user approved all three
changes and confirmed that community CI jobs share one host's Docker daemon.
Implementation is complete; real deployment acceptance is still blocked.

## Delivered changes

- Community deployment CI passes the requested image tag through explicit shared
  configuration, checks all six local application images before starting containers,
  and starts the docs image with the same tag. Development/production data paths
  and the lightweight runtime sandbox remain unchanged.
- The existing K8s skills preservation fix (`72c4703f3`, PR #3875) is retained.
  Regression coverage now compares every official ZIP name and byte, checks every
  checksum entry, and verifies actual extracted k8s/all package checksums.
- `--include-sandbox-full true` produces a separate
  `nexent-sandbox-full-<version>-<arch>.zip`, including when the main package is not
  compressed. It no longer changes the main package name or includes full in the
  main manifest. The attachment contains one full image, manifest, checksums,
  loaders/push helper and instructions; no deployment resources.
- Cached full images are reused only for the requested OS/architecture. A failed
  export or compression does not publish a partial attachment. Release workflows
  request and publish separate amd64/arm64 attachments to GitHub artifacts and OBS;
  manual and reusable workflow inputs remain optional by default.

## Executed checks

All five shell suites passed:

```bash
bash deploy/tests/test_docker_deploy_workflow.sh
bash deploy/tests/test_build_offline_package.sh
bash deploy/tests/test_common.sh
bash deploy/tests/test_images_build.sh
bash deploy/tests/test_load_images.sh
```

The CI regression failed before the fix because the workflow still contained its
version override. It now verifies six tag/mode combinations and missing-image
failure. Attachment regression failed before implementation because full changed
the main package name; it now verifies separate output, real ZIP extraction and
checksums, cached/mismatched architecture, source/prefix selection, custom main
name, saved full mode, Docker/ctr/push command routing and export/ZIP failures.
The pre-existing skills fix already passed its new assertions; no new production
change was needed for that item.

Three changed workflow YAML documents and all embedded shell scripts passed
syntax checks. Their actual version/name resolution step passed 32 combinations
of architecture, source inclusion, full attachment selection and Git ref/version.
Publication conditions, required-artifact errors and preflight order were also
checked. `bash -n` and `git diff --check` passed.

Image pull/save/load/push and container operations in these tests are mocked.
ZIP compression, extraction and checksum verification use real local tools. These
results do not prove live Docker/containerd import or successful deployment.

## Remaining acceptance

| Criterion | Local evidence | Required environment evidence | Status |
| --- | --- | --- | --- |
| AC-1: complete official skills offline | Complete ZIP/content/checksum checks pass | Identify the reported failing release package; deploy offline to K8s, compare shared PVC content and install an official skill | BLOCKED |
| AC-2: independent full image delivery | Package separation, architecture/source selection, helper routing and failure tests pass | Export/load actual full images on Docker/containerd; deploy with full mode; verify both architectures' published assets | BLOCKED |
| AC-3: CI tag consistency | Six tag/mode cases and missing-image preflight pass | Run on the authorized shared runner and compare container image IDs with build results | BLOCKED |

Docker server version 29.5.3 was read successfully. Further local image inventory
and Kubernetes access escalation requests were declined, so no real image or
cluster operations were performed. GitHub CLI authentication was invalid; no
workflow was dispatched and no artifacts were published. Docker Engine 18.09
compatibility is preserved by using existing tar export/import commands and
ordinary image inspection, but was not exercised on an 18.09 daemon.

The configured sibling `nexent-doc` repository and canonical module registry were
not present. The approved plan and temporary proposal/design/execution records
remain at `/tmp/nexent-deployment-delivery-evidence/`; canonical document filing
is pending. This file records implementation verification, not a replacement SPEC.

## Rollout and rollback

Run the fixed community workflow on the confirmed shared runner. Rebuild the
affected release package from a branch containing the skills fix. Select/download
the independent full attachment when needed; verify checksums, import or push it
separately, then deploy the main package with `--sandbox-mode full` and matching
version/source/prefix. Preserve default lightweight mode otherwise.

Rollback by reverting the corresponding change and rebuilding its artifacts. No
database migration, existing SQL edit or application API change is introduced.
