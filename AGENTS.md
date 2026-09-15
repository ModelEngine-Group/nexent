# Nexent project instructions

## Repository map

- `backend/` contains the FastAPI HTTP API; `sdk/nexent/` contains the agent framework.
- `frontend/` contains the Next.js UI. Deployment resources live in `deploy/`, `docker/`, and `k8s/`.
- Python tests live in `test/backend/` and `test/sdk/`.

## Shared constraints

- Write code comments, docstrings, TODOs, and configuration comments in English. User-facing strings may use supported languages; this does not prescribe conversation language.
- In backend/SDK Python code, centralize environment reads in `backend/consts/const.py`. Backend callers import from `consts.const`; SDK code accepts parameters and must not read environment variables or introduce `from_env()` methods.
- Every SQL file under `deploy/sql/` already merged into the target branch is immutable, including initialization and Supabase SQL. Do not edit, rename, or delete it. Add versioned migrations under `deploy/sql/migrations/`; application version is `APP_VERSION` in `backend/consts/const.py`.
- Preserve existing HTTP routes, payloads, and response contracts when applying conventions to new code.

## Load rules for the task

Before editing or reviewing these areas, read the linked skill and only its applicable references. Paths are relative to this root. Read files directly if the client has no skill loader; no package download is required. For cross-layer work, load each relevant skill. Documentation-only work does not require unrelated coding skills.

| Task or affected area | Entry point |
| --- | --- |
| Backend endpoints, services, database access, backend/SDK configuration, SQL migrations | [.agents/skills/nexent-backend/SKILL.md](.agents/skills/nexent-backend/SKILL.md) |
| Frontend pages, UI, hooks, API services, types, styles, localization | [.agents/skills/nexent-frontend/SKILL.md](.agents/skills/nexent-frontend/SKILL.md) |
| Writing, debugging, or reviewing Python unit tests | [.agents/skills/nexent-python-tests/SKILL.md](.agents/skills/nexent-python-tests/SKILL.md) |

These Markdown files are the maintained rules. `.cursor/rules/` contains compatibility entry points with the original Cursor triggers. Edit canonical rules when changing policy. See [migration decisions](docs/agent-rules-migration.md) when maintaining this setup.

## Development and verification

- Backend setup uses Python 3.11. From `backend/`, run `uv sync --extra data-process --extra test`; install the SDK with `uv pip install -e "../sdk[dev]"`.
- Run targeted tests from the root using the configured backend environment, for example `pytest test/backend/apps/test_agent_app.py -v`. The broader runner is `python test/run_all_test.py`. Confirm the interpreter works before testing.
- From `frontend/`, `npm run dev` starts development. `npm run check-all` runs type-check, lint, format checking, and build; individual checks are in `frontend/package.json`.
- Match verification to changed behavior and report checks actually run or blocked. For instruction-only edits, validate paths, skill metadata, scope, and rule coverage; application suites are unnecessary.
- Python imports follow standard library, third-party, then project order. SDK Ruff configuration uses a 119-character line limit.

## Docker compatibility

- Support Docker Engine 18.09 / API v1.39; the Compose CLI may be current.
- Newer daemon capabilities, including GPU device requests, cgroup namespace modes, and healthcheck `start_interval`, require an Engine version check and an 18.09-compatible fallback.
- Quote boolean-like and numeric values in Compose `environment` mappings. Schema boolean fields such as `privileged` and `external` remain booleans.
- Inspect current deployment scripts and `deploy/env/.env.example` for deployment work. Deployment execution remains limited to the user's authorized scope.
