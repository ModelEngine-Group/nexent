# HTTP layer

Applies to `backend/apps/**/*.py`.

## Boundary and compatibility

- Parse/validate inputs, invoke services, translate domain errors to HTTP, and return responses. Keep business logic out of apps.
- Read configuration from `consts.const` or pass explicit parameters. Preserve existing routes, payloads, and response structures.
- New collections use plural nouns and snake_case path segments; parameters use singular semantic names such as `{agent_id}`. Keep legacy prefixes such as `/agent`.
- Prefer resource-oriented CRUD routes; use action routes for non-CRUD behavior or compatibility.
- GET reads/lists; preserve legacy GET actions but introduce no new side-effecting GETs. POST creates, searches, or triggers actions. DELETE is idempotent. Prefer PUT for full updates and PATCH for partial updates while retaining legacy POST update routes.

## Requests and identity

- Inject authorization with `authorization: Optional[str] = Header(None)` where this is the endpoint convention. Use `utils.auth_utils` helpers such as `get_current_user_id` / `get_current_user_info`; pass `user_id` / `tenant_id` to services. Do not implement token parsing in routes.
- Prefer Pydantic models in `consts.model` for complex bodies; use `Body(..., embed=True)` for atomic named fields. Use `Query`, `Path`, and `Header` for the corresponding input locations.
- Recommended new list pagination is page 1, page size 20, and page-size bounds 1 through 100. Return `items` / `total` or an established response shape; support ordering/filters where appropriate.

## Responses and failures

- Ordinary JSON success uses `JSONResponse(status_code=HTTPStatus.OK, content=payload)` unless an established standard model or other response mode applies. Preserve streaming contracts.
- New responses use structured dictionaries consistent with nearby endpoints. Do not force a new envelope onto existing contracts.
- Map exceptions from `backend/consts/exceptions.py`: `UnauthorizedError` to 401, `LimitExceededError` to 429, domain parameter errors to 400 or established 406 behavior, and unexpected failures to 500. Log internal details without exposing them to users.
- Use a module-level `logging.getLogger(__name__)`; log useful events without sensitive data.
- Match module async/sync conventions. Await async services directly; do not create new event loops to invoke services.

Verify validation, identity propagation, response shape, and changed exception mappings.
