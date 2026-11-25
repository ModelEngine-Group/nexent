# Service layer

Start with `backend/management/services/<domain>/` for Management orchestration. Runtime execution lives under `backend/runtime/`, Ops logic under `backend/ops/services/` and `backend/ops/monitoring/`, and Data Process orchestration under `backend/data_process/services/`. Follow callers to the owner before adding a module.

- Orchestrate business behavior within the owning service and coordinate its persistence and SDK collaborators. Management and Runtime must not import each other's implementations. Shared contracts and adapters must not import either service's business code. Use the signed [AgentOS interface](agentos.md) for cross-service calls and callbacks.
- Return plain domain values; do not return web framework responses, raise `HTTPException`, or translate failures into HTTP status codes.
- Reuse domain exceptions in `backend/contracts/errors/`; declare new domain classes there when needed. Wrap lower-level failures at the appropriate boundary with `raise DomainError(...) from exc`.
- Existing exceptions include `AgentRunException`, `LimitExceededError`, `UnauthorizedError`, `SignatureValidationError`, and `MemoryPreparationException`. Inspect current definitions before use.
- Import configuration from `contracts.constants.environment` or accept parameters, then pass configuration into SDK calls. Do not read environment variables here.
- A service explicitly allowed to continue after database failure may catch an appropriate shared exception. Inspect what the database client actually raises; do not assume it wraps failures in a named custom exception.

Verify orchestration, return values, and domain failure propagation independently of HTTP mapping. For moved modules or dependency changes, consult [service layout tests](../../../../test/backend/management/test_service_directory_architecture.py) and [service isolation tests](../../../../test/backend/management/test_agent_runtime_boundaries.py).
