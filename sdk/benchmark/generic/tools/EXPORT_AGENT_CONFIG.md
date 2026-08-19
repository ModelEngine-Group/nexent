# Exporting Agent Configurations

[Chinese version](./EXPORT_AGENT_CONFIG.zh-CN.md)

`export_agent_config.py` reads an agent definition from PostgreSQL and writes a
YAML snapshot accepted by `run_benchmark.py`.

## Environment

The CLI currently reads database settings from the process environment or the
repository `.env` file.

| Variable | Default |
|---|---|
| `NEXENT_DB_HOST` | `localhost` |
| `NEXENT_DB_PORT` | `5434` |
| `NEXENT_DB_NAME` | `nexent` |
| `NEXENT_DB_USER` | `root` |
| `NEXENT_DB_PASSWORD` | Local development default |

Do not commit real credentials. Sensitive tool parameters are exported as
strict `{"$env": "VARIABLE_NAME"}` references.

## Usage

```bash
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py \
  --agent-id 7 \
  --output /tmp/agent_7.yaml

backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py \
  --name "Math Assistant" \
  --version 1 \
  --output /tmp/math_assistant_v1.yaml
```

Exactly one of `--agent-id` or `--name` is required. When `--version` is
omitted, the current agent version is exported.

Generated configurations are local artifacts and are ignored by default.
Promote a configuration into the committed standard set only after removing
tenant-specific data and replacing all secrets with environment references.

## Validation

Before using an exported file:

1. Review agent, tool, sub-agent, and skill metadata.
2. Confirm that every sensitive value is represented by `$env`.
3. Run `run_benchmark.py --dry-run --agent-config <path>`.
4. Keep the generated file outside the repository unless it is deliberately
   curated as a standard example.
