# Local Langfuse for Benchmarks

This directory contains the self-hosted Langfuse stack shared by Nexent benchmark runners and debugging tools.

## Start

```bash
cd sdk/benchmark/infra/langfuse
cp .env.example .env
# Replace every replace-me value in .env before continuing.
docker compose -p nexent-benchmark-langfuse up -d
```

The stack starts Langfuse web and worker services together with PostgreSQL, ClickHouse, Redis, and MinIO.

Verify the deployment:

```bash
curl -s http://localhost:3100/api/public/health
docker compose -p nexent-benchmark-langfuse ps
```

Open `http://localhost:3100` and sign in with the initialization credentials from `.env`.

## Configure Benchmark Clients

Export the Langfuse endpoint and project keys before running a benchmark:

```bash
set -a
source sdk/benchmark/infra/langfuse/.env
set +a
export LANGFUSE_HOST=http://localhost:3100
export LANGFUSE_PUBLIC_KEY="$LANGFUSE_INIT_PROJECT_PUBLIC_KEY"
export LANGFUSE_SECRET_KEY="$LANGFUSE_INIT_PROJECT_SECRET_KEY"
```

The generic runner connects directly to Langfuse; `ctx_debugger` is only needed for optional deep context traces.

## Stop

```bash
docker compose -p nexent-benchmark-langfuse down
```

To also remove local Langfuse data volumes:

```bash
docker compose -p nexent-benchmark-langfuse down -v
```

## Security

`.env` is ignored by Git and must never be committed.
`compose.yaml` publishes Langfuse web on host port 3100; restrict host access when the machine is reachable from a network.
Use a trusted reverse proxy and TLS before exposing the service beyond a development machine.
