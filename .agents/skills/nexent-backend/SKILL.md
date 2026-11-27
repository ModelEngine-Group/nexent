---
name: nexent-backend
description: Use when designing, implementing, debugging, or reviewing Nexent backend changes involving Gateway exposure and identity, FastAPI endpoints, Management and Runtime boundaries, AgentOS contracts, shared infrastructure adapters, services, relational schemas, persistence, SQL migrations, or backend/SDK configuration. Skip frontend-only work and unrelated SDK algorithms.
---

# Nexent backend changes

Repository paths below are relative to the root; reference links resolve from this skill directory.

1. Locate the owning service. For public routes, look up the method, path, and transport in the Gateway exposure registry, then confirm the target app's router registration. Start internal changes with the owning service and its callers.

   | Owner | Where to start |
   | --- | --- |
   | Gateway | `backend/gateway/` owns public exposure, external authentication, signed identity forwarding, and HTTP/SSE/WebSocket routing. |
   | Management | `backend/management/` owns product APIs and resource authorization, Agent definitions and versions, prepared run inputs, conversation messages, and evaluation and automation orchestration. |
   | Runtime | `backend/runtime/` owns Agent and model execution, builds SDK objects from prepared inputs, and manages execution state, cancellation, and the replayable event journal. |
   | Ops | `backend/ops/` owns operational APIs and supporting jobs for monitoring, trajectory inspection, and system configuration. |

   **AgentOS** is the versioned internal capability contract between independently deployable Management and Runtime processes. Its types live in `backend/contracts/`, its signed transport adapters in `infrastructure/`, and its endpoints in the owning services.

   **Infrastructure** provides technical adapters for storage, service transport, and observability. Services retain ownership of authorization, business workflows, and data lifecycle decisions. Shared HTTP assembly lives in `backend/http/server/`; the SDK supplies execution mechanisms through explicit inputs and dependencies.

   Treat Data Process as transitional. The migration SPEC assigns file cleansing to Management and model-dependent knowledge-base execution to Runtime.
2. Read only the references matching the work. For end-to-end changes, read each affected layer before editing.

| Work | Reference |
| --- | --- |
| HTTP routes, validation, identity, response/error mapping, external API failures returned to the frontend | [HTTP layer](references/http.md) |
| Service ownership, shared infrastructure, and domain errors | [Services](references/services.md) |
| AgentOS calls and callbacks, admission, replay, and event projection | [AgentOS](references/agentos.md) |
| Relational schema design, models, keys/indexes, queries, transactions, SQL migrations | [Database](references/database.md) |
| Environment configuration and SDK configuration parameters | [Configuration](references/configuration.md) |
| Threads, worker pools, blocking calls, background loops, streaming resource lifetime | [Thread lifecycle](references/thread-lifecycle.md) |

3. Preserve public contracts. Apply conventions to the changed scope; do not refactor unrelated legacy behavior merely to satisfy a rule.
