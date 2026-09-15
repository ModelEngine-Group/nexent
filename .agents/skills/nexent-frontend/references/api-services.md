# Frontend API services

- Keep endpoint definitions and base request behavior in `frontend/services/api.ts`; domain operations belong in matching `*Service.ts` modules.
- Use `API_ENDPOINTS`; do not hardcode URLs or concatenate endpoint strings in domain services. Add parameterized builders centrally when needed.
- Use `fetchWithErrorHandling`. Inspect its current return type and error behavior before parsing; preserve existing streaming/response contracts.
- Use shared `ApiError` and existing 401/499 session-expiration handling. Avoid duplicating or bypassing that behavior.
- Type request and response data separately; shared contracts belong in `frontend/types/` and may be re-exported where compatibility requires. Use generics for actual reuse.
- Handle transformations and useful error information; log through `frontend/lib/logger.ts`.
- Services must not depend on `app/` or `components/`. Verify endpoint selection, parsing, and changed error paths.
