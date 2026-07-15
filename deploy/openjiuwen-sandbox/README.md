# OpenJiuwen Fixed AIO Sandbox (Development)

This deployment mode connects every Nexent backend worker or replica to one
predeployed AIO Sandbox container. Nexent does not create, stop, rebuild, or
delete the container. Requests execute concurrently in the shared container;
there is no application-level execution lock, queue, or serial scheduler.

The mode is intended for development validation. Request workspaces prevent
normal requests from overwriting each other, but they are not an operating
system or tenant security boundary.

## 1. Start the fixed AIO Sandbox first

OpenJiuwen 0.1.15 documents the following AIO quick-start command:

```bash
docker run \
  --name nexent-openjiuwen-sandbox \
  --rm \
  -p 127.0.0.1:8080:8080 \
  --cpus 2 \
  --memory 2g \
  --pids-limit 256 \
  --security-opt seccomp=unconfined \
  -e WORKSPACE=/workspace \
  ghcr.io/agent-infra/sandbox:latest
```

`WORKSPACE=/workspace` is required by Nexent's default
`OPENJIUWEN_SANDBOX_WORKSPACE_ROOT=/workspace/nexent` layout. The image entrypoint
creates the directory and grants the sandbox runtime user write access. Without
this setting, Shell commands can return a non-zero exit code while the following
filesystem operation fails because `/workspace` was never created.

`seccomp=unconfined` follows the upstream development quick start and weakens
the container boundary. Do not treat this command as a production security
profile. The upstream image currently starts its supervisor as root, so it does
not satisfy the non-root baseline out of the box. A shared deployment should
use a reviewed or derived sandbox image and seccomp profile, a non-root user,
no privileged mode, no Docker socket, no host paths, no backend secrets,
explicit CPU/memory/PID/disk limits, and ingress-only network policy with
outbound access denied by default.

On some Docker Desktop environments, image `1.11.0` can start successfully but
an endpoint on a Docker `--internal` network is not reachable through a
published localhost port. The OpenJiuwen client can surface that connection
failure as `199004 ... [Errno 1] Operation not permitted`. Confirm the endpoint
with `curl` before changing container privileges. Do not solve the error by
adding `--privileged`.

For a backend that also runs in containers, prefer a dedicated internal network
and do not publish the Sandbox port to the host:

```bash
docker network create --internal nexent-sandbox-internal

docker run \
  --name nexent-openjiuwen-sandbox \
  --rm \
  --network nexent-sandbox-internal \
  --cpus 2 \
  --memory 2g \
  --pids-limit 256 \
  --security-opt seccomp=unconfined \
  -e WORKSPACE=/workspace \
  ghcr.io/agent-infra/sandbox:latest
```

Attach every backend worker or replica to the same internal network and use
`OPENJIUWEN_SANDBOX_BASE_URL=http://nexent-openjiuwen-sandbox:8080`. The
internal network has no external gateway, so Sandbox scripts cannot resolve or
reach public hosts or Nexent services on other Docker networks. A backend run
directly on the host cannot use this topology; the localhost quick start above
is only a development connectivity profile and needs a separate host firewall
or network policy to deny outbound traffic.

When the backend runs in Docker or Kubernetes, expose the same trusted internal
endpoint to every backend replica, for example
`http://nexent-openjiuwen-sandbox:8080`. Do not publish the endpoint publicly.

## 2. Enable it only through deployment configuration

Set these values in `deploy/env/.env` or the equivalent backend environment:

```dotenv
AGENT_RUNTIME_PROVIDER=openjiuwen
OPENJIUWEN_SANDBOX_ENABLED=true
OPENJIUWEN_SANDBOX_BASE_URL=http://host.docker.internal:8080
OPENJIUWEN_SANDBOX_PROVIDER=aio
OPENJIUWEN_SANDBOX_EXECUTION_TIMEOUT_SECONDS=300
OPENJIUWEN_SANDBOX_REQUEST_TIMEOUT_SECONDS=30
OPENJIUWEN_SANDBOX_WORKSPACE_ROOT=/workspace/nexent
```

Restart only the backend deployment after changing these values. No frontend
configuration, frontend rebuild, Agent field, database migration, HTTP request,
or SSE schema change is required.

At startup, each backend process registers its own process-local OpenJiuwen
`SysOperation`, pointing to the same endpoint, and performs a health probe. A
failed probe prevents that backend process from starting. Disabling the switch
prevents the sandbox extension from being loaded or contacted.

## 3. Shared-container execution behavior

Each Skill invocation uses a unique path:

```text
/workspace/nexent/<request_hash>/
├── input/
├── skills/<skill_name>/
├── output/
└── tmp/
```

Different users and replicas can enter the container at the same time. Staging,
process markers, artifact download, stop, and cleanup are scoped to the current
request. Stopping one request sends TERM/KILL only for its marker and does not
stop the container or another request.

The model sees only Nexent's existing `run_skill_script` tool. OpenJiuwen's
generated filesystem, shell, code, upload, download, background, and streaming
tools are not added to the ReActAgent ability manager. If the sandbox is
unavailable, Nexent fails closed and does not retry with a host subprocess.

## 4. Operational checks

Monitor backend logs and metrics for:

- `OpenJiuwen fixed sandbox started` and health/startup failures;
- Skill execution duration and concurrent failure rate;
- `sandbox_stage=resource`, `timeout`, `cancel`, `artifact`, or `cleanup`;
- host staging cleanup failures;
- stale `/workspace/nexent/<request_hash>` directories older than the maximum
  execution timeout;
- container CPU, memory, PID, disk, restart count, and AIO request latency.

Resource exhaustion affects all concurrent users of the shared container.
Return the controlled tool error to the caller, do not fall back to the backend
host, and restart or rebuild the fixed container when residue cannot be cleaned.
Schedule regular container replacement because a crashed worker or malicious
Skill can leave files or processes outside its request workspace.

## 5. Smoke test

With the sandbox and backend running, use an Agent containing
`RunSkillScriptTool` and execute a Python or Shell Skill that reads an attachment
and writes a file to `NEXENT_OUTPUT_DIR`. Verify that:

1. the result and artifact use the unchanged Nexent SSE payload;
2. two requests run concurrently instead of waiting on a lock or queue;
3. stopping one request does not stop the other;
4. the backend host never runs the Skill subprocess;
5. request workspaces and host staging directories are removed afterward.

The opt-in automated contract is:

```bash
OPENJIUWEN_SANDBOX_ENABLED=true \
OPENJIUWEN_SANDBOX_BASE_URL=http://127.0.0.1:8080 \
backend/.venv/bin/python -m pytest \
  test/backend/services/test_openjiuwen_sandbox_e2e.py -v
```
