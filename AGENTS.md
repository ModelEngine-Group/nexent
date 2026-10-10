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
| Requirement or bug lifecycle, SPEC traceability, and delivery gates | [.agents/skills/nexent-spec-coding/SKILL.md](.agents/skills/nexent-spec-coding/SKILL.md) |
| Requirement-driven Feature catalog, D1-D5 case-local tests and bindings, generated registry and Excel view under `test-e2e/` | [.agents/skills/nexent-test-assets/SKILL.md](.agents/skills/nexent-test-assets/SKILL.md) |
| Python unit tests for every product change: unit behavior, boundaries, errors and regressions | [.agents/skills/nexent-python-tests/SKILL.md](.agents/skills/nexent-python-tests/SKILL.md) |

These Markdown files are the maintained rules. `.cursor/rules/` contains compatibility entry points with the original Cursor triggers. Edit canonical rules when changing policy. See [migration decisions](docs/agent-rules-migration.md) when maintaining this setup.

## Development and verification

- Traditional UT and formal D1-D5 are permanently separate, complementary suites. Every product-code change must assess both; implement or reuse applicable UT and formal Cases. Do not manufacture edits or a five-stage quota. Non-behavior-only changes may use an explicit documented exemption; missing prerequisites are blockers, not exemptions.
- Before submitting a product-code PR, run relevant traditional UT locally. New/changed behavior needs success, boundary and error assertions; bugfixes need a regression that detects the defect (reuse is valid when demonstrated). PR CI must run its configured UT set; required-check enforcement belongs to GitHub branch protection and is not established by these instructions. Do not change workflows or remote protection without authorization.
- Preserve all existing D1 Cases and scripts; overlap with UT is not grounds for deletion, retirement or relabeling. New D1 should prove a component contract with real internal collaboration and controlled external boundaries; D3 proves inter-component/service/protocol runtime integration. Choose by proof boundary, not function calls or mocks. Use no extra layer when it adds no necessary evidence.
- Keep traditional UT results/coverage separate from formal functional results; frontend and Python coverage percentages are never combined. A collected script passing is not evidence that every written acceptance requirement was implemented. Record acceptance implementation gaps and distinguish execution from completeness.
- Backend setup uses Python 3.11. From `backend/`, run `uv sync --extra data-process --extra test`; install the SDK with `uv pip install -e "../sdk[dev]"`.
- Run targeted tests from the root using the configured backend environment, for example `pytest test/backend/apps/test_agent_app.py -v`. The broader runner is `python test/run_all_test.py`. Confirm the interpreter works before testing.
- Formal D1-D5 assets live in `test-e2e/`; use `python test-e2e/infra/tools/validate_test_assets.py --phase implementation` to check generated views and `python test-e2e/infra/tools/run_cases.py <Case-ID> --test-home <local-test-data>` for targeted execution. Keep machine-local configuration and results outside Git.
- From `frontend/`, `npm run dev` starts development. `npm run check-all` runs type-check, lint, format checking, and build; individual checks are in `frontend/package.json`.
- Match verification to changed behavior and report checks actually run or blocked. For instruction-only edits, validate paths, skill metadata, scope, and rule coverage; application suites are unnecessary.
- Python imports follow standard library, third-party, then project order. SDK Ruff configuration uses a 119-character line limit.

## Docker compatibility

- Support Docker Engine 18.09 / API v1.39; the Compose CLI may be current.
- Newer daemon capabilities, including GPU device requests, cgroup namespace modes, and healthcheck `start_interval`, require an Engine version check and an 18.09-compatible fallback.
- Quote boolean-like and numeric values in Compose `environment` mappings. Schema boolean fields such as `privileged` and `external` remain booleans.
- Inspect current deployment scripts and `deploy/env/.env.example` for deployment work. Deployment execution remains limited to the user's authorized scope.
