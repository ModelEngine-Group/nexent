---
name: spec-coding
description: Use for Nexent feature work, architecture changes, database/API changes, multi-file refactors, or any implementation that should be driven by SPEC documentation. Enforces documentation-first development through the Nexent Development SPECs Wiki: organize by implementation status, then feature scope, then lifecycle documents; update requirements, functional design, technical design, and development plan before coding.
license: Complete terms in LICENSE.txt
---

# Spec Coding

Use this skill for Nexent coding work that changes product behavior, architecture, data models, APIs, persistence, runtime flows, or multiple modules. The goal is controlled implementation: document first, develop from the approved docs, and keep the Wiki as the source of truth.

## Source of Truth

Use the Feishu Wiki named `Nexent Development SPECs`.

Top-level organization is by implementation status:

```text
00 - Wiki Governance and Reading Guide
10 - Proposed Specs
20 - In Development Specs
30 - Implemented Specs
40 - Paused or Superseded Specs
90 - Templates and Standards
```

Inside each status section, organize by feature scope. Inside each feature scope, use lifecycle documents:

```text
<Feature Scope>
├── 00 - Requirement Analysis
├── 01 - Functional Design
├── 02 - Technical Design
└── 03 - Development Plan
```

If a parent page has children, its body may include a `Quick Access` table, but only for direct children (depth 1). Every entry in `Quick Access` must be a clickable link to the child page. Do not maintain a global directory in page bodies; the Wiki UI already provides that.

## Mandatory Workflow

Before writing code:

1. Identify the feature scope and current implementation status.
2. Locate or create the feature scope under the correct status section.
3. Ensure these lifecycle pages exist:
   - `00 - Requirement Analysis`
   - `01 - Functional Design`
   - `02 - Technical Design`
   - `03 - Development Plan`
4. Read the relevant lifecycle pages before editing code.
5. If the docs are missing or stale, update the Wiki first.
6. Only implement code that is traceable to the approved lifecycle docs.

During coding:

- Keep the implementation aligned with the `03 - Development Plan` PR/phase breakdown.
- If code discoveries invalidate the docs, stop broad implementation and update the relevant lifecycle page first.
- Keep acceptance criteria, tests, migrations, and compatibility requirements synchronized with the docs.

After coding:

- Update the relevant lifecycle page with implementation notes only when they change the plan, design, or acceptance criteria.
- Move the feature scope between status sections when its lifecycle status changes:
  - `Proposed Specs` -> `In Development Specs` when implementation starts.
  - `In Development Specs` -> `Implemented Specs` after implementation and acceptance.
  - Any active status -> `Paused or Superseded Specs` when paused, abandoned, or replaced.

## Lifecycle Page Responsibilities

`00 - Requirement Analysis`:

- Problem statement
- Goals and non-goals
- User or system impact
- Constraints
- Risks

`01 - Functional Design`:

- User-visible or system-visible behavior
- Capability boundaries
- Functional decomposition
- Error, empty, compatibility, and migration behavior where relevant

`02 - Technical Design`:

- Architecture
- Interfaces and contracts
- Data models and schema changes
- Runtime integration points
- Backward compatibility strategy

`03 - Development Plan`:

- Phase and PR breakdown
- File/module ownership
- Acceptance criteria
- Test plan
- Rollout and fallback notes

## Nexent-Specific Checks

For backend work, preserve the app/service/const layer boundaries described in `AGENTS.md`.

For environment variables, keep `backend/consts/const.py` as the single source of truth. SDK code must not read environment variables directly.

For DB schema changes, update all required locations:

- versioned migration under `docker/sql/*.sql` or the project migration location in use
- Docker Compose fresh deploy init SQL
- K8s fresh deploy init SQL
- `APP_VERSION` if the project versioning rule requires it

For tests, follow the project pytest conventions and add focused coverage matching the documented acceptance criteria.

## When Documentation Can Be Lightweight

Tiny mechanical fixes may use a short existing scope note instead of a full lifecycle set only when all are true:

- The change is single-purpose and low risk.
- No API, DB, runtime contract, or user-visible behavior changes.
- No cross-module coordination is needed.
- The user explicitly wants a small fix.

Even then, mention the relevant existing SPEC or explain why no SPEC update was needed.

