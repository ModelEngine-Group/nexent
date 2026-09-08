# Service layer

Applies to `backend/services/**/*.py`.

- Orchestrate business behavior and coordinate database/SDK collaborators.
- Return plain domain values; do not return web framework responses, raise `HTTPException`, or translate failures into HTTP status codes.
- Reuse domain exceptions in `backend/consts/exceptions.py`; declare new domain classes there when needed. Wrap lower-level failures at the appropriate boundary with `raise DomainError(...) from exc`.
- Existing exceptions include `AgentRunException`, `LimitExceededError`, `UnauthorizedError`, `SignatureValidationError`, and `MemoryPreparationException`. Inspect current definitions before use.
- Import configuration from `consts.const` or accept parameters, then pass configuration into SDK calls. Do not read environment variables here.
- A service explicitly allowed to continue after database failure may catch an appropriate shared exception. Inspect what the database client actually raises; do not assume it wraps failures in a named custom exception.

Verify orchestration, return values, and domain failure propagation independently of HTTP mapping.
