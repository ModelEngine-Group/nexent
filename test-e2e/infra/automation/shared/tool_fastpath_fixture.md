# Deployed tool fast-path acceptance fixture

`TFP-D3-001` and `TFP-D4-001` use the **mock** profile: only the OpenAI HTTP
provider is controlled. Nexent APIs, authentication, the SDK Agent loop,
official tools, Docker execution, PostgreSQL history, MinIO and the browser
are real. These scripts do not implement the existing D3 `real_smoke` profile.

## Prepare a disposable deployment

Use the current checkout's SDK in the runtime container. Preflight compares
the deployed `nexent_agent.py`, `tool_fastpath.py` and `sandbox.py` SHA-256
fingerprints to this checkout. The runtime Python interpreter must be the
image's `/opt/backend/.venv/bin/python`.

Configure the disposable runtime with:

```dotenv
NEXENT_SANDBOX_DEFAULT_LEVEL=docker
NEXENT_SANDBOX_DEFAULT_SCOPE=session
NEXENT_SANDBOX_WORKSPACE_MODE=bind
NEXENT_TOOL_FASTPATH_ENABLED=true
```

The deployment needs the current compatible sandbox image and a reachable
kernel service, bind workspace access, healthy PostgreSQL/Redis/MinIO, and
Agent trace export to Langfuse. An explicit tool allowlist must include the
official `ReadSkillConfigTool`. Use a dedicated fixture tenant/account with
memory pre-search disabled; do not change shared tenants' settings for this
test. No concurrent runs may use this fixture's workspace during D3's Docker
event observation. The tests never run Compose, replace an image or restart
the deployment.

Provision `tenant_a_admin` and `tenant_b_user` in the test home's existing
`config/users.yaml` and credentials in `config/secrets.env`. They must belong
to different tenants. The D4 browser signs in as the same `tenant_a_admin`.

## Provision the skill and private fixture

Import the maintained directory `test-e2e/infra/assets/tool-fastpath/skill/`
as a skill named `tfp-verification` in the disposable tenant. A ZIP containing
`SKILL.md`, `config/schema.yaml`, `config/config.yaml` and `scripts/report.py`
can be uploaded through the existing skill UI. Enable access for the fixture
admin. Its schema has exactly `marker` and `value`; the script creates one
`tfp-<nonce>.txt` file in its output working directory. Do not add runtime
paths, provider credentials or unrelated scripts to this fixture skill.

Copy `tool_fastpath_fixture.example.json` into the machine-local test home,
restrict its permissions to `0600`, and replace the example values. Set
`NEXENT_TFP_FIXTURE` to that JSON path in `config/daily.env` (or the process
environment). The maintained JSON schema rejects extra fields.

`runtime_container` is the exact disposable Nexent runtime container.
`skill_id` and `skill_name` refer to the pre-provisioned skill. `config` is
the effective per-Agent override; `value` must be an integer from 1 to 1000.
`workspace_mount_id` is the root bind mapping's `SandboxWorkspace.mount_id`,
computed by the deployed SDK from its resolved host root and container root.
Use that root mapping, not a per-run path. It is the label
`com.nexent.workspace` on the runtime's session sandboxes. Obtain it from the
SDK mapping or a known disposable session sandbox; an all-zero example is
not a valid observed mapping.

Set `langfuse.url` to that deployment's project API URL and configure the two
named keys in `config/secrets.env`. The JSON records key **names**, never key
values. The API account needs read access to traces and observations.
Authenticated trace preflight occurs before any model or Agent creation.
Incomplete trace pagination, absent completed trace, empty telemetry, failed
warm-up or a local fallback all fail acceptance.

The normal test runner owns `services/test-assets/server.py` and provides
`NEXENT_TEST_ASSETS_LOCAL_URL` for host-local controls and
`NEXENT_TEST_ASSETS_URL` for runtime access. The runtime must be able to reach
the latter URL. Scenarios use random nonces and a fixture-specific system
constraint; model health checks and title generation cannot consume Agent
turns, even when they use the same model and token budget. No global model
or existing Agent configuration is replaced.

Both bindings declare `preparation.anchors: true`, which is the existing
suite mechanism for starting controlled services and verifying test anchors.
Use the maintained test-home anchor/users/model configuration for this
disposable deployment. The direct D3 `run_cases.py` path does not start those
services itself; use the suite worker below, or supply an already runner-owned
controlled service when invoking that direct path.

## Execute and inspect

Run through the existing configured test interpreter:

```sh
python test-e2e/infra/scripts/run-suite.py run --test-home <local-test-home> --case TFP-D3-001 --case TFP-D4-001 --execute
```

D3 executes independent cold and promoted API runs plus a promoted run with
a controlled post-run assertion failure. It compares SSE to terminal
history, reads complete traces, checks exact session container creation and
destruction counts, verifies report bytes and denies another tenant's access.
The controlled failure passes only if all cleanup checks also succeed.

D4 runs cold and promoted tasks in separate owned chats. It verifies exact
tool cards and executed-code cards before and after reload, compares persisted
history, and downloads the Markdown-linked report with the real browser,
checking the filename and bytes. It never intercepts product HTTP responses.

Owned resource IDs are journaled under each run's `RESULT_DIR/runtime/`.
The D4 `tfp-fixture.json` receipt contains no credentials and has `0600`
permissions. Cleanup stops only owned conversations, waits for terminal
persistence, deletes only nonce-matched report objects and owned conversations,
then removes the test Agent, test model and provider scenario. Cleanup errors
are retained without hiding the original test failure. The prepared skill
and shared service deployment are retained.

Missing deployment, fixture, identities, trace credentials or browser
prerequisites are blockers. Static validation, collection and harness unit
tests are not deployed E2E passes. Keep the formal Case status `blocked`
until those prerequisites and actual execution evidence exist.
