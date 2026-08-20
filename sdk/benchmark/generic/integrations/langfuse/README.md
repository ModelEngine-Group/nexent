# Benchmark Webhook Server

[Chinese version](./README.zh-CN.md)

`webhook_server.py` accepts Langfuse Custom Experiment payloads and executes
benchmark or rescore jobs in background threads.

## Start

```bash
backend/.venv/bin/python sdk/benchmark/generic/integrations/langfuse/webhook_server.py \
  --host 127.0.0.1 \
  --port 8090
```

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /webhook` | Start a run or rescore request |
| `GET /health` | Return service health |
| `GET /evaluators` | List registered evaluators |

Example run request:

```bash
curl --fail-with-body http://127.0.0.1:8090/webhook \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_name": "gaia-level1-web-search",
    "config": {
      "mode": "run",
      "run_name": "webhook-smoke-YYYYMMDD",
      "evaluators": ["gaia_exact_match"],
      "max_steps": 15,
      "temperature": 0,
      "language": "en",
      "agent_config": "configs/gaia_solver.yaml"
    }
  }'
```

The process currently loads runtime settings from the repository `.env`.
Do not expose this server directly to the public internet. Use the controls in
[DEPLOY.md](./DEPLOY.md).

Use immutable run names and verify the resulting Langfuse links, evaluator
scores, and manifest before trusting a webhook-triggered experiment.
