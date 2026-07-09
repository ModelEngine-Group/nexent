# AGENTS

<!-- Skills section removed -->

<skills_system priority="1">

## Available Skills

<!-- SKILLS_TABLE_START -->
<usage>
When users ask to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke: `npx openskills read <skill-name>` (run in your shell)
  - For multiple: `npx openskills read skill-one,skill-two`
- The skill content will load with detailed instructions on how to complete the task
- Base directory provided in output for resolving bundled resources (references/, scripts/, assets/)

Usage notes:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in your context
- Each skill invocation is stateless
</usage>

<available_skills>

<skill>
<name>spec-coding</name>
<description>Use for Nexent feature work, architecture changes, database/API changes, multi-file refactors, or any implementation that should be driven by SPEC documentation. Enforces documentation-first development through the Nexent Development SPECs Wiki: organize by implementation status, then feature scope, then lifecycle documents; update requirements, functional design, technical design, and development plan before coding.</description>
<location>project</location>
</skill>

<skill>
<name>prompts-writing</name>
<description>Create, refine, and optimize high-quality YAML prompts for AI assistants. Use when working with prompt templates, system prompts, agent prompts, or any prompt engineering tasks. Provides structure guidelines, template patterns, and quality standards for YAML-based prompts.</description>
<location>project</location>
</skill>

<skill>
<name>skill-creator</name>
<description>Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.</description>
<location>project</location>
</skill>

</available_skills>
<!-- SKILLS_TABLE_END -->

</skills_system>

---

## Project Overview

Nexent is a zero-code platform for auto-generating AI agents. Monorepo with:
- `backend/` - FastAPI HTTP API
- `sdk/nexent/` - Core agent framework (pip package)
- `frontend/` - Next.js web UI
- `docker/` & `k8s/` - Deployment configs

---

## SPEC Coding Workflow (Mandatory)

For any Nexent feature work, architecture change, database/API change, multi-file refactor, runtime behavior change, or other implementation that can affect product behavior, **invoke and follow the `spec-coding` skill before coding**.

Development must be documentation-first:
- Use the Feishu Wiki `Nexent Development SPECs` as the source of truth.
- Organize SPEC documents by implementation status first, then feature Scope, then lifecycle document type.
- The expected lifecycle pages are `00 - Requirement Analysis`, `01 - Functional Design`, `02 - Technical Design`, and `03 - Development Plan`.
- Read the relevant lifecycle pages before editing code.
- If required SPEC pages are missing or stale, update the Wiki first, then implement.
- Code changes must trace back to the documented requirements, design, development plan, and acceptance criteria.
- If implementation discoveries invalidate the SPEC, update the relevant lifecycle page before continuing broad code changes.

Only tiny mechanical fixes may skip a full SPEC update, and only when they do not change API, DB schema, runtime contracts, cross-module behavior, or user-visible behavior. In that case, state why no SPEC update was needed.

Development must be test-verified against the documented acceptance criteria:
- Unit tests should relact the acceptance criteria and edge cases from the SPEC.
- Unit tests must reach 90% coverage for any new or modified module.
- Integration tests must verify cross-module behavior and runtime flows.
- For all frontend-affected changes, `playwright` must be used to verify user-visible behavior and acceptance criteria.
- For all backend-affected changes, `curl` or `wget` must be used to verify API behavior and acceptance criteria.
- For all SDK-affacted changes, when actual model calls are required to perform functional test, ask the user to provide one, and test with `LangFuse` to trace every step's input and output.

---

## Developer Commands

### Backend (Python 3.11)

```bash
# Setup
cd backend && uv sync --extra data-process --extra test

# Install SDK for development
cd backend && uv pip install -e "../sdk[dev]"
```

### Run Tests

```bash
# From project root, with backend venv activated
source backend/.venv/bin/activate && python test/run_all_test.py

# Single test file
pytest test/backend/apps/test_agent_app.py -v
```

### Frontend (Next.js)

```bash
cd frontend
npm run dev          # Development server
npm run check-all    # type-check + lint + format + build
```

### Docker Deployment

```bash
cd docker
cp deploy/env/.env.example deploy/env/.env  # Fill required configs
bash deploy.sh        # Interactive deployment
```

---

## Architecture

### Environment Variables

**Single source of truth**: `backend/consts/const.py`

- NO direct `os.getenv()` / `os.environ.get()` outside this file
- SDK (`sdk/nexent/`) NEVER reads env vars - accepts config via parameters
- Services read from `consts.const` and pass to SDK

### Backend Layer Structure

| Layer | Path | Responsibility |
|-------|------|----------------|
| Apps | `backend/apps/` | HTTP boundary: parse input, call services, map exceptions to HTTP |
| Services | `backend/services/` | Business logic orchestration, raise domain exceptions |
| Consts | `backend/consts/` | Env vars (`const.py`), exceptions (`exceptions.py`), error codes |

**Exception flow**: Services raise domain exceptions → Apps map to HTTP status codes

---

## Database Migrations

**Location**: `docker/sql/*.sql` (versioned migration scripts)

**Critical rule**: When adding columns/tables via migration script:
- Update `docker/init.sql` (Docker Compose fresh deploy)
- Update `k8s/helm/nexent/charts/nexent-common/files/init.sql` (K8s fresh deploy)

**Version**: Tracked in `backend/consts/const.py` as `APP_VERSION`

---

## Testing Conventions

- pytest only (no unittest)
- Mock at import site with fully-qualified path:
  ```python
  mocker.patch("backend.services.agent_service.AgentService.run", return_value={...})
  ```
- Async tests: `@pytest.mark.asyncio`
- Test structure: `test/backend/` and `test/sdk/`

---

## Code Style

- English-only comments and docstrings (enforced by `.cursor/rules/english_comments.mdc`)
- Import order: stdlib → third-party → project
- Line length: 119 (sdk ruff config)

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/consts/const.py` | All env var definitions, APP_VERSION |
| `backend/consts/exceptions.py` | Domain exceptions (AgentRunException, LimitExceededError, etc.) |
| `docker/init.sql` | Database schema for Docker Compose |
| `k8s/helm/.../init.sql` | Database schema for Kubernetes |
| `test/run_all_test.py` | Test runner with coverage |

---

## Reference Files

Existing instruction files with detailed rules:
- `CLAUDE.md` - Backend architecture, env var management, app/service layer rules
- `.cursor/rules/environment_variable.mdc` - Env var centralization
- `.cursor/rules/pytest_unit_test_rules.mdc` - Testing patterns
- `.cursor/rules/english_comments.mdc` - Comment language enforcement
