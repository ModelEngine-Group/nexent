# Nexent A2A mock service

This directory contains a standalone A2A test double. It does not contain formal D1-D5 cases, manifests, or product test automation.

## One-command deployment

From the repository root, run `python3 test/mock-services/deploy.py up a2a`.
Use `python` on Windows. For an existing stack under Compose project `compose`,
add `--project compose` to avoid starting a second stack on occupied ports.
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

## Local container startup

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
