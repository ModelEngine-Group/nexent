# Bundled Default Agents Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make industry-specific official agent bundles appear as platform-level, read-only Agent Repository templates immediately after Nexent installation, while tenant copies remain fully editable and publishable.

**Architecture:** Keep official bundle contents outside the Nexent source repository and inject one selected profile into the installer package. On backend startup, safely load the selected ZIP bundles, create or update their source agents under a reserved tenant identifier, and upsert repository snapshots. Extend existing repository reads to include the reserved tenant while keeping all management writes tenant-scoped; reuse the existing repository-copy import path for tenant-owned copies.

**Tech Stack:** Python, FastAPI, SQLAlchemy/PostgreSQL, pytest, TypeScript/React, Docker Compose, Kubernetes/Helm, Bash deployment tests.

---

## Task 1: Define official profile and reserved-tenant configuration

**Files:**
- Modify: `backend/consts/const.py`
- Modify: `deploy/env/.env.example`
- Test: `test/backend/consts/test_const.py` or the existing constants test module

**Step 1: Write the failing tests**

Add tests asserting that the official tenant/user constants are stable and that profile/path resolution honors explicit environment values without leaking unrelated profiles.

**Step 2: Run tests to verify they fail**

Run: `pytest test/backend/consts/test_const.py -q`

Expected: FAIL because the official constants and configuration helpers do not exist.

**Step 3: Implement the minimal configuration**

Add constants for the reserved official tenant and system user, plus environment-backed profile/path defaults. Keep the path resolved to one selected profile; do not scan sibling industry profiles.

Document the new variables in `deploy/env/.env.example`.

**Step 4: Run tests to verify they pass**

Run: `pytest test/backend/consts/test_const.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/consts/const.py deploy/env/.env.example test/backend/consts/test_const.py
git commit -m "feat(agents): configure official agent profile"
```

## Task 2: Add safe official bundle loading

**Files:**
- Create: `backend/services/official_agent_bundle_service.py`
- Modify: `backend/consts/model.py` only if existing snapshot models need a reusable bundle model
- Test: `test/backend/services/test_official_agent_bundle_service.py`

**Step 1: Write the failing tests**

Cover profile directory enumeration, ZIP extraction, required `agent.json`, malformed JSON, path traversal rejection, skill ZIP loading, text knowledge-base seed loading, binary seed path preservation, and profile isolation.

**Step 2: Run tests to verify they fail**

Run: `pytest test/backend/services/test_official_agent_bundle_service.py -q`

Expected: FAIL because the loader does not exist.

**Step 3: Implement the loader**

Implement a small loader that:

- accepts the configured official-agent directory;
- enumerates only supported bundle files/directories;
- extracts each ZIP into a temporary directory;
- rejects absolute paths and `..` traversal;
- validates the agent snapshot before returning it;
- attaches declared skills and knowledge-base seed documents;
- returns bundle key, version/card metadata, and snapshot data;
- never writes bundle content into the Nexent source tree.

Keep filesystem and model validation separate from persistence and startup orchestration.

**Step 4: Run tests to verify they pass**

Run: `pytest test/backend/services/test_official_agent_bundle_service.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/services/official_agent_bundle_service.py backend/consts/model.py test/backend/services/test_official_agent_bundle_service.py
git commit -m "feat(agents): load official agent bundles safely"
```

## Task 3: Implement reserved-tenant source-agent synchronization

**Files:**
- Create: `backend/services/official_agent_sync_service.py`
- Modify: `backend/database/agent_db.py`
- Modify: `backend/database/agent_repository_db.py`
- Modify: `backend/services/agent_service.py` only where existing import/create helpers need explicit system tenant/user overrides
- Test: `test/backend/services/test_official_agent_sync_service.py`
- Test: `test/backend/database/test_agent_db.py`

**Step 1: Write the failing tests**

Test first synchronization, repeated synchronization, changed bundle version, missing bundle, one-bundle failure isolation, stable source `agent_id` reuse, and preservation of tenant copies.

**Step 2: Run tests to verify they fail**

Run: `pytest test/backend/services/test_official_agent_sync_service.py -q`

Expected: FAIL because the synchronizer and official lookup helpers do not exist.

**Step 3: Implement synchronization**

Implement per-bundle synchronization under `OFFICIAL_AGENT_TENANT_ID` and `OFFICIAL_AGENT_USER_ID`:

- locate the existing source agent using a stable bundle/root name within the reserved tenant;
- create it only when absent;
- reuse its `agent_id` on later starts;
- build the repository snapshot with status `shared`;
- reuse `upsert_agent_repository_record()` keyed by stable source `agent_id` and reserved tenant;
- update official snapshots when bundle content/version changes;
- isolate transactions and exceptions per bundle;
- log profile, bundle key, version, and failure reason.

Do not add database columns or tables. Do not import official agents into real tenants during startup.

**Step 4: Add startup invocation**

Hook the synchronizer into the existing backend startup/lifecycle after database readiness. Make it non-blocking with respect to service availability and ensure it cannot run concurrently in a way that creates duplicate source agents.

**Step 5: Run tests to verify they pass**

Run: `pytest test/backend/services/test_official_agent_sync_service.py test/backend/database/test_agent_db.py -q`

Expected: PASS.

**Step 6: Commit**

```bash
git add backend/services/official_agent_sync_service.py backend/database/agent_db.py backend/database/agent_repository_db.py backend/services/agent_service.py test/backend/services/test_official_agent_sync_service.py test/backend/database/test_agent_db.py
git commit -m "feat(agents): sync official templates on startup"
```

## Task 4: Expose official entries through existing repository reads

**Files:**
- Modify: `backend/database/agent_repository_db.py`
- Modify: `backend/services/agent_repository_service.py`
- Modify: `backend/apps/agent_repository_app.py` only if endpoint behavior needs explicit handling
- Test: `test/backend/services/test_agent_repository_service.py`
- Test: `test/backend/app/test_agent_repository_app.py`

**Step 1: Write the failing tests**

Add tests proving a tenant sees its own shared entries plus official entries, can open official details, and can import an official entry into its own tenant. Add tests proving a tenant cannot edit, review, unshare, or delete official entries.

**Step 2: Run tests to verify they fail**

Run: `pytest test/backend/services/test_agent_repository_service.py test/backend/app/test_agent_repository_app.py -q`

Expected: FAIL because current reads are scoped only to the current publisher tenant.

**Step 3: Implement visibility and permissions**

- Extend summary/detail lookup to treat the reserved tenant as globally readable.
- Keep status filtering restricted to `shared` for official entries.
- Preserve current-tenant ownership checks for all management writes.
- Make repository import always pass the current authenticated tenant/user to the existing agent import helpers.
- Keep download increments working for official repository IDs.
- Ensure official source agents never appear in a tenant's My Agents result.

Do not add a new official-agent API, source field, or schema migration.

**Step 4: Run tests to verify they pass**

Run: `pytest test/backend/services/test_agent_repository_service.py test/backend/app/test_agent_repository_app.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/database/agent_repository_db.py backend/services/agent_repository_service.py backend/apps/agent_repository_app.py test/backend/services/test_agent_repository_service.py test/backend/app/test_agent_repository_app.py
git commit -m "feat(repository): expose official agent templates"
```

## Task 5: Mark official entries in the existing repository UI

**Files:**
- Modify: `frontend/types/agentRepository.ts`
- Modify: `frontend/app/[locale]/agent-space/**` relevant repository-list/detail components
- Modify: `frontend/public/locales/zh/common.json`
- Modify: `frontend/public/locales/en/common.json`
- Test: existing frontend repository tests, or add the smallest focused component test available

**Step 1: Write the failing test**

Test that an official listing is marked as official, exposes copy/import, and does not expose tenant management actions.

**Step 2: Run the test to verify it fails**

Run the repository-specific frontend test command for the focused test.

Expected: FAIL because the frontend has no official-entry marker.

**Step 3: Implement the UI changes**

Derive official status from the reserved publisher tenant value returned by the API, add localized official labels, hide edit/review/takedown controls, and keep the existing copy flow unchanged.

**Step 4: Run frontend verification**

Run: `pnpm tsc --noEmit` from `frontend` and the focused frontend test command.

Expected: PASS with no new TypeScript errors.

**Step 5: Commit**

```bash
git add frontend/types/agentRepository.ts frontend/app/[locale]/agent-space frontend/public/locales/zh/common.json frontend/public/locales/en/common.json
git commit -m "feat(repository): label official agent templates"
```

## Task 6: Package and inject industry resources during deployment

**Files:**
- Modify: `deploy/offline/build_offline_package.sh`
- Modify: `deploy/docker/deploy.sh`
- Modify: `deploy/docker/compose/docker-compose.yml`
- Modify: `deploy/docker/compose/docker-compose.prod.yml`
- Modify: `deploy/k8s/deploy.sh`
- Modify: relevant Helm templates/values under `deploy/k8s/helm/nexent/`
- Modify: `deploy/env/.env.example`
- Test: `deploy/tests/test_build_offline_package.sh`
- Test: relevant deployment shell tests

**Step 1: Write failing deployment tests**

Cover selected profile inclusion in an offline package, no inclusion of other profiles, Docker read-only resource mount, Kubernetes resource injection, default profile behavior, and missing-profile diagnostics.

**Step 2: Run tests to verify they fail**

Run: `bash deploy/tests/test_build_offline_package.sh`

Expected: FAIL because official-agent package inputs and mounts are not supported.

**Step 3: Implement package/deployment support**

Add an explicit installer input for a selected external resource package/profile. Copy only the selected profile into the final package, persist its configuration, mount it read-only at `OFFICIAL_AGENTS_PATH`, and keep the Nexent source repository free of official bundle contents. Ensure Docker and Kubernetes use equivalent runtime paths.

**Step 4: Run deployment tests**

Run: `bash deploy/tests/test_build_offline_package.sh` and the focused deployment test scripts.

Expected: PASS.

**Step 5: Commit**

```bash
git add deploy/offline/build_offline_package.sh deploy/docker/deploy.sh deploy/docker/compose deploy/k8s/deploy.sh deploy/k8s/helm/nexent deploy/env/.env.example deploy/tests
git commit -m "feat(deploy): package industry agent profiles"
```

## Task 7: Run focused and full verification

**Files:**
- Modify: only files required by failing verification
- Test: all tests listed below

**Step 1: Run focused backend tests**

```bash
pytest test/backend/services/test_official_agent_bundle_service.py test/backend/services/test_official_agent_sync_service.py test/backend/services/test_agent_repository_service.py test/backend/app/test_agent_repository_app.py -q
```

Expected: PASS.

**Step 2: Run deployment tests**

```bash
bash deploy/tests/test_build_offline_package.sh
```

Expected: PASS.

**Step 3: Run frontend verification**

```bash
cd frontend
pnpm tsc --noEmit
```

Expected: PASS with no new errors.

**Step 4: Run broader relevant test suites**

Run the existing backend repository/import test suites and the relevant Docker/Kubernetes shell test suite. Record any pre-existing failures separately from failures introduced by this change.

**Step 5: Perform implementation self-check**

- No official bundle content was added to the Nexent source repository.
- No database field/table/migration was added.
- Official source agents use only the reserved tenant.
- Tenant copies use the current tenant and retain normal edit/publish permissions.
- Official entries are globally readable but management-write protected.
- Only the configured industry profile is loaded.
- No unrelated user untracked files were staged.

**Step 6: Commit any final verification-only fixes**

If fixes are required, create one additional commit for this implementation round using the repository commit convention.
