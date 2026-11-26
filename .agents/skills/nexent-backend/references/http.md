# HTTP layer

Start with the owning API under `backend/management/api/`, `backend/runtime/api/`, or `backend/ops/api/`. Runtime also registers internal routes from `backend/runtime/agentos/`. Shared FastAPI assembly lives in `backend/http/server/`.

## Boundary and compatibility

- Parse/validate inputs, invoke services, translate domain errors to HTTP, and return responses. Keep business logic out of apps.
- Preserve existing routes, public aliases, payloads, and response structures. For a public route change, verify both the target app's router registration and the entry in [`backend/gateway/exposure/registry.json`](../../../../backend/gateway/exposure/registry.json). Check the exact method, path, target, transport, and allowed credential type. Router registration alone does not expose a route. For Partner or Northbound operations with a capability gate, verify both permitted and excluded capability settings.
- New collections use plural nouns and snake_case path segments; parameters use singular semantic names such as `{agent_id}`. Keep legacy prefixes such as `/agent`.
- Prefer resource-oriented CRUD routes; use action routes for non-CRUD behavior or compatibility.
- GET reads/lists; preserve legacy GET actions but introduce no new side-effecting GETs. POST creates, searches, or triggers actions. DELETE is idempotent. Prefer PUT for full updates and PATCH for partial updates while retaining legacy POST update routes.

## Requests and identity

- Gateway verifies external credentials and signs forwarded identity. Use the target service's existing verified identity dependency and enforce resource authorization in the owning service. In Management, follow the identity helpers in `management.services.permission.identity.session` where applicable. Pass verified user and tenant IDs to business operations. Internal AgentOS routes use the service principal from [AgentOS](agentos.md).
- Use Pydantic for complex request bodies. Place shared schemas in the owning module under `contracts/`; use `Body(..., embed=True)` for atomic named fields. Use `Query`, `Path`, and `Header` for the corresponding input locations.
- Recommended new list pagination is page 1, page size 20, and page-size bounds 1 through 100. Return `items` / `total` or an established response shape; support ordering/filters where appropriate.

## Responses and failures

- Ordinary JSON success uses `JSONResponse(status_code=HTTPStatus.OK, content=payload)` unless an established standard model or other response mode applies. Preserve streaming contracts.
- New responses use structured dictionaries consistent with nearby endpoints. Do not force a new envelope onto existing contracts.
- Use domain errors from `backend/contracts/errors/` where applicable. Keep each endpoint's existing mappings and safe error payloads. For streams, distinguish an HTTP error before response headers from an error event in an established stream. Log internal details without exposing them to users.
- Before adding or changing a business error, check `backend/contracts/errors/codes.py` and reuse an existing `ErrorCode` with the same meaning. If no existing code fits, allocate an unused six-digit string in the appropriate module and category using `XXYYZZ` (module, category, sequence), preserving leading zeros.
- For reused and new codes, verify the HTTP status in `ERROR_CODE_HTTP_STATUS` against the endpoint's semantics. Check the frontend error-code mapping and localized messages, and update them as needed so the UI shows the intended message.
- When a Nexent endpoint calls an external platform, map upstream failures to Nexent domain errors at the integration boundary. Return a stable Nexent error code in the existing response shape and choose the HTTP status according to the Nexent endpoint's semantics.
- Reserve HTTP 401 on authenticated endpoints for missing, invalid, or expired Nexent credentials. Never pass an upstream 401 through to the frontend. For example, if a model provider rejects an API key, return the Nexent error for provider authentication failure with an appropriate non-401 status. The frontend uses 401 to clear the Nexent session.
- Use a module-level `logging.getLogger(__name__)`; log useful events without sensitive data.
- Match module async/sync conventions. Await async services directly; do not create new event loops to invoke services.
