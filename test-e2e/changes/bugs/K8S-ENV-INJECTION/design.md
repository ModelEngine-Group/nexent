# Design — Kubernetes deployment environment injection

## Context and functional boundary

Change: `K8S-ENV-INJECTION`; owner: `F-173`, rule `F-173-RULE-02`.
The user approved a repository-local design instead of the unavailable external SPEC repository.
The current branch is `dev/k8s-env`; initial unrelated state is the untracked `nexent-test-suite/` directory.

`deploy/docker/compose/docker-compose.prod.yml` loads `.env` for Config, Runtime,
MCP, Northbound and Data Process; Config and Runtime additionally load `monitoring.env`.
`deploy/k8s/deploy.sh` currently renders a fixed set of common ConfigMap/Secret fields.
Inspection on 2026-10-14 found 91 local `.env` keys absent from those shared templates,
including HITL, runtime thread limits and AIDP. Some absent keys have dedicated injection paths.
This establishes a configuration-transfer defect, without claiming live cluster behavior.

The capability consumes the existing deployment env files and finalized deployment options,
produces Helm values and Secret resources, and starts backend containers with their effective
configuration. Existing credential generation, split infrastructure/application releases,
service contracts, defaults and deployment selection remain in place.

## Final design

- Observe assignments executed by Bash while sourcing each trusted env file in a separate
  fail-fast shell. Emit only declared variable names, with their final values encoded as
  Base64. This preserves actual Bash quoting, substitutions and multiline values without
  dumping inherited host variables or mistaking assignment-looking multiline content for keys.
- Add `nexent-common.envFiles.rootData` and `monitoringData`, defaulting to empty mappings.
  Render `nexent-env` and `nexent-monitoring-env` even when empty for direct Helm compatibility.
- Backend envFrom order is common ConfigMap, root env Secret, monitoring Secret where
  applicable, then finalized credentials Secret. Explicit env has highest priority.
- Preserve Kubernetes mode, namespace, SQL startup mode/checksum, selected MCP/sandbox images
  and sandbox execution level as explicit platform settings. Do not give Web or infrastructure
  the new Secret references. Keep Web's dedicated configuration injection.
- Render application Secret values after credential setup. Prepare file payloads before
  writing, write atomically with mode 0600, and propagate failures without printing env values.
  The rollout checksum includes the deterministic effective file payloads and platform options.
  Rendering fresh maps removes deleted keys; the next deployment recreates backend containers.
- Missing optional monitoring input produces an empty map; required root input errors stop
  application Secret rendering. The existing .env initialization/merge process is unchanged.
- Follow-up cleanup removes the fixed per-variable backend copy in the runtime values
  renderer. Common Chart defaults remain available for direct Helm use. Keep only timezone,
  Web's Northbound URL, Redis URL as the runtime-state fallback input, and the part-processor
  count as the worker-concurrency input, plus Web's dedicated upload limit. Final credentials,
  infrastructure settings, SQL content and explicit container overrides are retained.

## Current fix acceptance

| AC | Observable requirement | Proof |
| --- | --- | --- |
| AC-001 | All file-declared keys, including new/unknown and empty keys, preserve loaded values; host-only keys are excluded. Invalid input publishes no partial payload or secrets in errors. | Traditional UT; runtime portion of K8S-ENV-D5-001 |
| AC-002 | Five backend services reference root env; only Config/Runtime reference monitoring; effective precedence preserves finalized credentials and explicit platform values. Web/infrastructure never reference the new Secrets. | Helm UT; K8S-ENV-D5-001 |
| AC-003 | A redeployment changes modified values, admits new keys, removes deleted keys, and changes the Pod environment checksum. Equivalent ordering/comments preserve the checksum. | Traditional UT; K8S-ENV-D5-001 |
| AC-004 | Direct Helm defaults render valid empty env Secrets. Generated application Secret values are atomic and mode 0600; failure preserves the previous file. | Traditional UT |
| AC-005 | Real test resources are created only in a new run-scoped namespace on an explicitly selected isolated cluster and are cleaned after success/failure; no local real .env or existing release is mutated. | K8S-ENV-D5-001 |
| AC-006 | Ordinary backend variables use the complete env Secret without fixed runtime-value copies. Web configuration, derived defaults, finalized credentials and direct Helm defaults retain their behavior. | Traditional UT; reuse K8S-ENV-D5-001 for the backend injection boundary |

## Traditional UT + D1-D5 responsibilities

| Feature / rule / AC | Traditional UT | D1 | D2 | D3 | D4 | D5 | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-173-RULE-02 / AC-001,003,004 | Add renderer and Helm composition assertions | N/A | N/A | N/A | N/A | K8S-ENV-D5-001 | UT proves isolated generation; D5 proves actual Kubernetes environment injection/update. |
| F-173-RULE-02 / AC-002,005 | Add static composition/precedence assertions | N/A | N/A | N/A | N/A | K8S-ENV-D5-001 | No changed HTTP, browser or model boundary. |
| Retained sandbox option selection | Existing deploy/tests/test_common.sh | N/A | N/A | N/A | N/A | DEP-AUTO-7177AC18CCE799DD | Unchanged formal regression, separate from the new runtime case. |
| F-173-RULE-02 / AC-006 | Strengthen the existing renderer/composition UT and CAS shell regression | N/A | N/A | N/A | N/A | Reuse K8S-ENV-D5-001 | No new proof boundary or Case is required for removal of redundant mapping. |

Existing tests were inspected: `deploy/tests/test_common.sh` checks selected CAS mappings,
rollout annotations and checksum normalization; `test/backend/consts/test_runtime_thread_config.py`
checks application constants but does not prove deployment injection; the sandbox D5 script
checks option dispatch and persistence. None asserts complete envFrom injection or live deletion.
No duplicate D1 is added. Other deployment feature history remains outside this fix.

Before cleanup, the runtime renderer duplicates backend file keys into the common ConfigMap,
while the complete root Secret already overrides those keys. The existing Web UT checks only
timezone/upload limit, and the six Helm precedence variants do not check derived defaults or
use the runtime values renderer. Extend those assertions with representative CAS/OAuth,
model-path and Data Process values, custom Web Northbound URL, Redis fallback, worker count,
empty values and deleted-key fallback. The old CAS shell regression checks the presence of
fixed rendering strings; replace that implementation-dependent check with actual Secret data.

## Test implementation and execution limits

Use synthetic env files and temporary output directories for UT and Helm rendering.
The D5 primary script belongs beside its Case, uses the production renderer and rendered
backend env configuration, and runs small probe Deployments to inspect env resolution without
starting business services or requiring model providers. Probe images are explicit test assets.
Use existing D5 mutation/isolation gates plus an explicit test context; never fall back to the
operator's current context. Missing prerequisites raise a dependency blocker before any cluster
command. Do not execute the live D5 against the current machine's existing cluster in this task.

## Acceptance traceability

| AC | Code areas | Traditional UT | Formal case | Evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-001 | `deploy/k8s/env.sh`; `render_runtime_secret_values` | `test/backend/deploy/test_k8s_env_injection.py`: value preservation, empty files, unknown keys, host exclusion, loading/encoding errors | K8S-ENV-D5-001 / AC-001 | Local UT PASS; live runtime not executed | LOCAL PASS; RUNTIME BLOCKED |
| AC-002 | Common env Secrets; five backend Deployments; platform env helper | Same UT selector: defaults, service scope, Web mapping, six deployment/sandbox combinations and precedence | K8S-ENV-D5-001 / AC-002 | Helm assertions and lint PASS; omission mutation detected | LOCAL PASS; RUNTIME BLOCKED |
| AC-003 | Fresh Secret maps; environment rollout checksum | Same UT selector: added/changed/deleted keys, order/comment normalization, sandbox mode changes, Pod annotations | K8S-ENV-D5-001 / AC-003 | Local generation and render PASS; actual replacement not executed | LOCAL PASS; RUNTIME BLOCKED |
| AC-004 | Atomic private writer; Helm defaults | Same UT selector: 0600 permissions, no leftover temporary files, previous values preserved on failure, empty Secret maps | N/A: isolated file/render contract | UT and default Helm rendering PASS | PASS |
| AC-005 | Case-local prerequisite gates, explicit context, run-owned namespace and cleanup | N/A: runtime risk boundary | K8S-ENV-D5-001 / AC-004 | Runner stops at the disabled mutation gate before any kubectl command; live cleanup unverified | BLOCKED |
| AC-006 | Reduced runtime values renderer and retained common Chart defaults | Existing UT selector: representative backend overrides, missing-key fallback, Web proxy URL, Redis/worker derivation and zero/empty inputs | Reuse K8S-ENV-D5-001 | 24 UT PASS; shell and local D5 composition PASS; live runtime blocked | LOCAL PASS; RUNTIME BLOCKED |

UT, shell regression, manifest rendering, asset validation and actual cluster execution results
must remain distinct. A passing render is not a passing Kubernetes runtime acceptance result.

## Delivery evidence — 2026-10-14

Traditional UT command:

```bash
backend/.venv/bin/python -m pytest test/backend/deploy/test_k8s_env_injection.py -q
```

Initial result: **20 passed**. The tests use synthetic files and exercise the production renderer and
Helm templates. As a regression sensitivity check, removing the `nexent-env` references in a
temporary Chart copy makes the precedence/composition assertion fail. This is a local proof,
not Kubernetes runtime execution.

`helm lint deploy/k8s/helm/nexent`, Bash syntax checks for both changed shell files, and
`git diff --check` passed. `deploy/tests/test_common.sh` and
`deploy/tests/test_build_offline_package.sh` passed in an isolated deployment copy, with
mock Docker/image packaging operations and synthetic deployment files. Both unchanged
workflow inputs required by the offline regression were copied as read-only fixtures; no
repository workflow was edited.

Strict formal design and implementation validation passed using the current change and Case
selectors. Generated Feature/registry/Excel views were regenerated; they are not execution
evidence. Final implementation drift validation uses:

```bash
backend/.venv/bin/python test-e2e/infra/tools/validate_test_assets.py \
  --phase implementation --require-ut-change K8S-ENV-INJECTION \
  --require-acceptance-case K8S-ENV-D5-001
```

Formal execution used the machine-local test home
`/private/tmp/nexent-k8s-env-tests-_cs5_iy0` with mutation disabled:

```bash
D5_ENABLE_MUTATING_DEPLOYMENT=false backend/.venv/bin/python \
  test-e2e/infra/tools/run_cases.py \
  DEP-AUTO-7177AC18CCE799DD K8S-ENV-D5-001 \
  --test-home /private/tmp/nexent-k8s-env-tests-_cs5_iy0
```

| Case | Script execution | Acceptance status | Local evidence, relative to test home |
| --- | --- | --- | --- |
| DEP-AUTO-7177AC18CCE799DD | PASS | UNREVIEWED: historical Case has no acceptance bindings | `runs/repository-local/20261014T025348490977Z-DEP-AUTO-7177AC18CCE799DD/status.json` |
| K8S-ENV-D5-001 | BLOCKED_BY_DEPENDENCY | Not passed: runner records FAIL for unexecuted bound obligations and UNREVIEWED semantic completeness | `runs/repository-local/20261014T025349909489Z-K8S-ENV-D5-001/status.json`, `checkpoints/results.jsonl`, `acceptance-execution.json` |

The new Case stops at `D5_ENABLE_MUTATING_DEPLOYMENT=false`. An authorized isolated cluster,
explicit context and probe image were not provided for this task, so no cluster command ran.
Collection and the Case's synthetic render/probe-resource construction were checked locally:
two fixture variants, five probe Deployments, three Secrets, service scope and differing
rollout checksums passed. Actual container values, live updates and resource cleanup remain
required runtime proof, not an exemption or a completed acceptance claim.

The first legacy common-script regression in the original checkout appended template defaults
to the local `.env` as an existing help-command side effect. The exact original bytes were
restored, and later shell regressions ran only in the isolated copy. Final `.env` SHA-256
matches the initial value:
`5978f5bba93f1ec8147177f9c391e589e51758509acbef0870d450cb3f1f72b2`.
No existing cluster deployment, merged SQL, business interface or CI configuration was changed.

## Cleanup follow-up evidence — 2026-10-14

The user authorized cleanup of redundant fixed rendering. The application runtime values
renderer now keeps four common inputs (timezone, Web Northbound URL, Redis URL and processor
count) and the Web upload limit. Backend CAS/OAuth, voice, model paths, storage/service
connections, limits and Data Process overrides are supplied by the complete file Secret.
Common Chart defaults, SQL rendering, credentials, platform parameters and infrastructure
rendering remain available through their existing paths.

The same traditional UT command now reports **24 passed**. Added assertions check that
ordinary backend fields are absent from generated common runtime values and remain effective
through Secret injection, removed fields recover Chart defaults, custom Web proxy/upload/TZ
settings survive, Redis fallback and worker concurrency follow their inputs (including zero
and empty strings), and direct Helm overrides still work. Existing input-error, private-write,
precedence and deployment/sandbox tests continue passing.

The updated `deploy/tests/test_common.sh` passes in the isolated deployment copy. Its CAS
regression now checks actual generic Secret payloads instead of requiring a fixed mapping
string in the deployment script. Helm lint, Bash syntax and diff checks pass. The D5 Case
now renders runtime values as well as Secret values and checks CAS overrides plus derived
Redis/worker values. Its two local fixture/probe-composition variants pass without cluster
commands; this remains local evidence only.

The affected formal selection was rerun with the same mutation-disabled command:

| Case | Script execution | Acceptance status | Local evidence, relative to the same test home |
| --- | --- | --- | --- |
| DEP-AUTO-7177AC18CCE799DD | PASS | UNREVIEWED historical acceptance | `runs/repository-local/20261014T031959790881Z-DEP-AUTO-7177AC18CCE799DD/status.json` |
| K8S-ENV-D5-001 | BLOCKED_BY_DEPENDENCY | Live acceptance not passed; mutation gate disabled before any cluster command | `runs/repository-local/20261014T032001105423Z-K8S-ENV-D5-001/status.json` |

Strict design and implementation validation with regeneration passed for the updated
contracts and script. The isolated-cluster runtime blocker remains; cleanup does not change
the task's deployment authorization or the `.env` preservation requirement.
