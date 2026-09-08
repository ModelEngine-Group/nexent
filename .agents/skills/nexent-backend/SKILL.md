---
name: nexent-backend
description: Use when designing, implementing, debugging, or reviewing Nexent relational schemas, FastAPI endpoints, backend services, database access, SQL migrations, or backend/SDK configuration. Includes table/field naming, types, JSONB boundaries, audit fields, keys, and indexes even before code paths exist. Skip frontend-only work and unrelated SDK algorithms.
---

# Nexent backend changes

Repository paths below are relative to the root; reference links resolve from this skill directory.

1. Identify the affected boundary and inspect existing callers and contracts. Apps handle HTTP, services orchestrate business logic, and database modules own persistence.
2. Read only the references matching the work. For end-to-end changes, read each affected layer before editing.

| Work | Reference |
| --- | --- |
| HTTP routes, validation, identity, response/error mapping | [HTTP layer](references/http.md) |
| Business orchestration and domain errors | [Services](references/services.md) |
| Relational schema design, models, keys/indexes, queries, transactions, SQL migrations | [Database](references/database.md) |
| Environment configuration and SDK configuration parameters | [Configuration](references/configuration.md) |

3. Preserve public contracts. Apply conventions to the changed scope; do not refactor unrelated legacy behavior merely to satisfy a rule.
4. Verify affected success and failure behavior. For Python unit tests, use `nexent-python-tests` linked from root `AGENTS.md`. Unit-test mocks do not establish live-integration acceptance.
5. Report references consulted, affected contracts, and verification results. Resolve material contract conflicts using concrete evidence; routine implementation choices do not require additional permission.
