# Service layer

## Service ownership

- Put public product orchestration under `backend/management/services/<domain>/`. Management authorizes tenant resources, owns Agent configuration and conversation records, and schedules automation and evaluation. It sends authorized, versioned run inputs to Runtime and projects Runtime events into product messages.
- Put execution under `backend/runtime/`. Runtime validates and resolves prepared inputs, constructs SDK objects, runs Agents and models, and manages tool and sandbox resources, cancellation, and run events. Keep run state under Runtime ownership and conversation state under Management ownership. For model administration, Management owns the public API, tenant permission checks, and resource bindings. Runtime owns model record changes, provider checks, and inference.
- Put exposure and external identity policy in `backend/gateway/`. Keep resource-specific authorization in the owning service. Put operational APIs and supporting jobs in `backend/ops/`, including monitoring, trajectory inspection, and system configuration.
- Use the signed [AgentOS interface](agentos.md) for calls and callbacks between Management and Runtime. Each service must start without the other's source tree. Shared contracts and adapters also remain independent of service implementations.

## Infrastructure and SDK

- Use the repository-root `infrastructure/` for technical capabilities with explicit interfaces. Examples include PostgreSQL access in `rdb/`, Redis state and events in `redis/`, object and vector storage clients, AgentOS transport, and trace I/O. Choose the narrow adapter matching the caller's data access and lifecycle needs.
- Keep authorization, transaction scope, and choices about which business records to read or write with the owning service. A shared database or adapter does not grant access to another service's repositories or replace an AgentOS operation. For example, Gateway uses a scoped read-only identity adapter, and Runtime uses shared Redis primitives while owning run admission and event lifecycle.
- Pass parameters and injectable dependencies into `sdk/nexent/`. The SDK owns reusable execution mechanisms and provider adapters. Service code assembles them with tenant, resource, and deployment context.

## Service implementation
- Return plain domain values; do not return web framework responses, raise `HTTPException`, or translate failures into HTTP status codes.
- Reuse domain exceptions in `backend/contracts/errors/`; declare new domain classes there when needed. Wrap lower-level failures at the appropriate boundary with `raise DomainError(...) from exc`.
- Existing exceptions include `AgentRunException`, `LimitExceededError`, `UnauthorizedError`, `SignatureValidationError`, and `MemoryPreparationException`. Inspect current definitions before use.
- Import configuration from `contracts.constants.environment` or accept parameters, then pass configuration into SDK calls. Do not read environment variables here.
- A service explicitly allowed to continue after database failure may catch an appropriate shared exception. Inspect what the database client actually raises; do not assume it wraps failures in a named custom exception.

Verify orchestration, return values, and domain failure propagation independently of HTTP mapping. For moved modules or dependency changes, consult [service layout tests](../../../../test/backend/management/test_service_directory_architecture.py) and [service isolation tests](../../../../test/backend/management/test_agent_runtime_boundaries.py).
