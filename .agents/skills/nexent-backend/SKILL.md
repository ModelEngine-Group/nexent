---
name: nexent-backend
description: Use when designing, implementing, debugging, or reviewing Nexent backend changes involving Gateway exposure and identity, FastAPI endpoints, Management and Runtime boundaries, AgentOS contracts, services, relational schemas, persistence, SQL migrations, or backend/SDK configuration. Skip frontend-only work and unrelated SDK algorithms.
---

# Nexent backend changes

Repository paths below are relative to the root; reference links resolve from this skill directory.

1. Locate the owning service. For public routes, look up the method, path, and transport in the Gateway exposure registry, then confirm the target app's router registration. Start internal changes with the owning service and its callers.

   | Owner | Where to start |
   | --- | --- |
   | Gateway | `backend/gateway/` for external identity, exposure policy, and forwarding |
   | Management | `backend/management/` for resource authorization, snapshots, conversation projection, and business orchestration |
   | Runtime | `backend/runtime/` for Agent and model execution, run state, and event streaming |
   | Ops | `backend/ops/` for trajectories, monitoring, and operational configuration |
   | Data Process | `backend/http/data_process_service.py` and `backend/data_process/` for data-processing API and task execution |

   Shared HTTP assembly lives in `backend/http/server/`, typed contracts in `backend/contracts/`, and shared adapters in the repository-root `infrastructure/`.
2. Read only the references matching the work. For end-to-end changes, read each affected layer before editing.

| Work | Reference |
| --- | --- |
| HTTP routes, validation, identity, response/error mapping | [HTTP layer](references/http.md) |
| Business orchestration and domain errors | [Services](references/services.md) |
| AgentOS calls and callbacks, admission, replay, and event projection | [AgentOS](references/agentos.md) |
| Relational schema design, models, keys/indexes, queries, transactions, SQL migrations | [Database](references/database.md) |
| Environment configuration and SDK configuration parameters | [Configuration](references/configuration.md) |
| Threads, worker pools, blocking calls, background loops, streaming resource lifetime | [Thread lifecycle](references/thread-lifecycle.md) |

3. Preserve public contracts. Apply conventions to the changed scope; do not refactor unrelated legacy behavior merely to satisfy a rule.
4. Verify affected success and failure behavior. For Python unit tests, use `nexent-python-tests` linked from root `AGENTS.md`. Unit-test mocks do not establish live-integration acceptance.
5. Report references consulted, affected contracts, and verification results. Resolve material contract conflicts using concrete evidence; routine implementation choices do not require additional permission.
