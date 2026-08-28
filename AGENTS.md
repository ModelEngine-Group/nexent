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

### Docker Compatibility

- Keep Docker deployments compatible with Docker Engine 18.09 (API v1.39). The Docker Compose CLI may be a current
  version; do not assume that the Compose CLI itself is legacy.
- Do not require daemon capabilities introduced after API v1.39, such as GPU device requests, cgroup namespace modes,
  or healthcheck `start_interval`, unless an Engine version check and an 18.09-compatible fallback are provided.
- Values under an `environment` mapping must be strings. Always quote YAML boolean-like and numeric values such as
  `true`, `false`, `yes`, `no`, `on`, `off`, `0022`, and port numbers.
- Boolean fields defined by the Compose schema, such as `privileged` and `external`, should remain native booleans.

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

**Location**: `deploy/sql/`

**Critical rule**: Every `.sql` file that already exists in the target branch is immutable.

- This rule applies to all migration, init, and Supabase SQL files without exception.
- Do not modify, rename, or delete an existing SQL file after it has been merged.
- Make database changes only by adding a new versioned migration file under `deploy/sql/migrations/`.

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
