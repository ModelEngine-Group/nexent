# Nexent A2A mock service

This directory contains a standalone A2A test double. It does not contain formal D1-D5 cases, manifests, or product test automation.

## One-command deployment

Run from the repository root. On Windows (Git Bash or PowerShell), for the
existing project named `compose`:

```bash
python test/mock-services/deploy.py list
python test/mock-services/deploy.py up a2a --project compose
python test/mock-services/deploy.py status a2a --project compose
python test/mock-services/deploy.py logs a2a --project compose
python test/mock-services/deploy.py stop a2a --project compose
```

Run only the operation needed: `stop` intentionally stops the Mock.
For a fresh installation, omit `--project compose`. On Ubuntu/Linux use
`python3` instead of `python`. Inspect `docker compose ls -a` first and use the
same project for every operation; project names are not OS-specific.

If Windows reports `Python was not found ... Microsoft Store`, `python3`
points to a Windows placeholder and the script has not started. Verify
`python --version` (or `py -3 --version`) and use that interpreter instead.
See [the deployment guide](../README.md) for standalone mode, status, logs,
stop commands, and registration of additional Mock services.

## Endpoints

- `/basic`, `/idkey`, `/jwt`, and `/both` expose mounted official A2A SDK applications.
- `/.well-known/agent-card.json`, `/v1`, `/message:send`, and `/message:stream` are available below each agent prefix.
- `/healthz` and `/readyz` expose process and dependency readiness.
- `/__dev/jwt?agent=jwt|both` mints short-lived test tokens.
- `/__test/scenario`, `/__test/reset`, and `/__test/observations` are protected by `X-A2A-Control-Token`.

The `both` profile accepts either `X-HW-ID + X-HW-APPKEY` or `X-HW-ID + Authorization`. It does not require all three credentials.
Protocol invocations must send the `A2A-Version: 1.0` header required by the official SDK.

## Manual container startup (alternative)

Prefer the unified deployment entry point above. The manual commands below
use the legacy default project `compose`, start the base stack and proxy
separately, and do not attach the product-network overlay. Do not mix them
with a running `nexent-mock-a2a` project on the same ports.

From the repository root:

```bash
docker compose -f test/compose/compose.a2a.yaml up --build
```

Use the container-network URL `http://a2a-agent:8888` from other services. The host mapping is intended only for development.

Start the optional transport-fault proxy after the base stack has created the shared network:

```bash
docker compose -f test/compose/compose.a2a-faults.yaml up -d
```

It creates `a2a-agent` and `nacos-a2a` proxies on host ports `18888` and `18848`. Configure latency, timeout, bandwidth, or connection-reset toxics through the Toxiproxy API on port `8474`.

Nacos 3.2.1 requires Base64 auth token and identity variables during process startup even in the no-auth profile. The Compose file contains local-test defaults; override all three values on a shared host.
The A2A Admin API always requires an administrator token. On a fresh test container the mock initializes the configured administrator, logs in, and then registers the Agent Card; no manual console visit is required.

## Control example

```bash
curl -X POST http://127.0.0.1:8888/__test/scenario \
  -H 'Content-Type: application/json' \
  -H 'X-A2A-Control-Token: local-test-control' \
  -d '{"name":"server-error"}'
```

Never use production credentials in this service. Request observations redact authorization and application-key values.

## Unit tests

The core tests do not start Nexent or register formal test assets:

```bash
python -m unittest discover -s tests -v
```
