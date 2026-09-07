# Deploying the Benchmark Webhook

[Chinese version](./DEPLOY.zh-CN.md)

The webhook server is optional. Prefer direct CLI execution unless Langfuse
Custom Experiment integration is required.

## Local start

```bash
backend/.venv/bin/python sdk/benchmark/generic/integrations/langfuse/webhook_server.py \
  --host 127.0.0.1 \
  --port 8090
```

Verify locally:

```bash
curl --fail http://127.0.0.1:8090/health
```

## Exposure options

- Use a temporary tunnel for short-lived local testing.
- Use an authenticated reverse proxy for long-running environments.
- Expose only the webhook path when possible.
- Keep health and evaluator endpoints read-only.
- Never expose repository files, `.env`, Langfuse credentials, model keys, or
  database credentials.

A production-style deployment should provide TLS, request authentication,
request-size limits, rate limits, access logs, and a process supervisor.

## Langfuse setup

Configure the Custom Experiment webhook URL as:

```text
https://<benchmark-host>/webhook
```

Send a one-item run first and confirm the dataset run, trace, score, and manifest
before allowing larger experiments.

The Chinese companion document retains the detailed ngrok and reverse-proxy
examples. Replace every host, credential, and filesystem location before use.
