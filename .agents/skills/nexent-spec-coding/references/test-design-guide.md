# D1 Test Design Guide

Use this guide while writing or revising `design.md`. It defines the pre-implementation test design for in-scope requirements and scenarios. D1 covers isolated unit and component behavior. API, database full-stack, Playwright, real-model, Agent-runtime, security, reliability, and other system checks remain separate verification layers.

## Required design content

Build a coverage inventory from every in-scope requirement and scenario, including relevant design contracts such as SDK schemas, adapters, serialization, stable event identity, state transitions, and validation rules. Give each requirement a stable feature ID such as `[AUTH-001]`. Every in-scope scenario maps to at least one independently verifiable case ID.

Include these items in `design.md`:

- D1 scope and explicit later-layer exclusions;
- scenario-to-case traceability rules;
- separate `FE-COMP`, `BE-UT`, and `SDK-UT` case tables for applicable cases;
- the test-first implementation and acceptance flow;
- recommended test-file grouping without requiring final paths before implementation.

Design review fails when an in-scope scenario has no case, a case lacks observable assertions, a case crosses the D1 boundary, or changed requirements leave the matrix stale. Create `task.md` only after human review confirms the matrix is complete and implementable.

## Choose the lowest proving layer

| Layer | Use for | Boundary |
| --- | --- | --- |
| `BE-UT` | Python functions, service logic, validation and state machines | Do not start the full system |
| `SDK-UT` | SDK schemas, adapters, serialization and event metadata | Do not call real external services |
| `FE-COMP` | React components, hooks, reducers, stores and forms | Do not start a real browser |

Assign each case to the lowest layer that proves its behavior. Record HTTP/database full-stack checks, browser journeys, real AI runtime checks, and other later-layer verification separately. D1 success cannot establish those results.

## Case table schema

Use one row per independently verifiable behavior. Parameterize only when inputs share setup, execution path, and assertions.

| Column | Required content |
| --- | --- |
| Case ID | Stable ID: `UT-FE-<area>-NNN`, `UT-BE-<area>-NNN`, or `UT-SDK-<area>-NNN` |
| Feature ID | Stable ID copied from the owning requirement |
| Level-1 module | Registered product capability from the canonical SPEC module registry |
| Level-2 module | Registered level-2 module, or `-` when the SPEC omits level 2 |
| Responsibility | Smallest user-visible or runtime responsibility under test |
| Title | Concrete behavior and normal/error/boundary path when useful |
| Layer | Exactly one of `FE-COMP`, `BE-UT`, or `SDK-UT` |
| Priority | `P0`, `P1`, or `P2`, based on business and regression risk |
| Scenario-based | `Yes` for interaction-oriented component cases; otherwise `No` unless the project defines another meaning |
| Journey | Existing E2E journey ID, or `-`; do not invent one |
| Preconditions | Minimal fixture state, flags, permissions, versions and unit setup |
| Local assets/config | Fixed fixtures or local assets; `None` when absent; never credentials |
| Steps | Numbered actions naming inputs, unit boundary, injected dependencies, user events and controlled faults |
| Expected results/assertions | Exact outputs, state transitions, dependency arguments/counts, errors and forbidden side effects |
| External dependency policy | Normally `NO_EXTERNAL`: local code, components, fixed fixtures and mocks only; no full system, browser or real model |

Do not require operational result columns such as daily CI stage, blocking policy, failure artifact, final code path, source URL, or tags during design unless the project explicitly asks for them.

## Case quality rules

- A title covers one behavior. Preconditions stay minimal. Steps identify the actual unit and concrete state or input.
- Assertions are implementable without guessing. Add forbidden-side-effect assertions where relevant, including no model call, persistence write, cross-session contamination, stale-state overwrite, downstream execution, or sensitive-data disclosure.
- Permission cases assert rejection and non-disclosure. Concurrency or isolation cases use distinct contexts and assert both directions of non-contamination. Component interaction cases use user events and assert accessible state where relevant.
- Fixed fixtures and mocks provide isolation or controlled fault injection. Keep external services out of D1. Do not make unsupported future behavior pass by expectation; keep it out of scope until the requirement changes.
- Row count is not semantic proof. Reviewers confirm that each case's steps and assertions actually prove its owning scenario.

## Test-first and acceptance flow

1. Before implementation, enumerate in-scope scenarios and design contracts, assign feature and case IDs, record later-layer exclusions, and review the matrix.
2. Add or update D1 tests before the corresponding production behavior. Bind each repository test to its case ID in its name, marker, docstring, or adjacent metadata. For a bug, retain a focused reproduction that fails before the fix when feasible.
3. Run the smallest relevant case group. Confirm new or corrected behavior fails for the expected reason before changing production logic when the repository and change permit a meaningful red step. If scaffolding, generated artifacts, or another concrete constraint makes this impossible, record the reason in `task.md`; the designed case is still required.
4. Implement the minimum approved production change needed to satisfy the case, rerun the smallest group, then run the complete affected D1 group.
5. A case passes only when every listed assertion and forbidden-side-effect check passes. Missing, unimplemented, skipped, or expected-failure cases do not pass unless the approved SPEC scope changes. Keep product, test, and environment failures distinct.
6. After D1 passes, run the separate verification layers required by the changed behavior. Do not infer API, browser, real-model, Agent-runtime, security, reliability, or full-system acceptance from D1.
7. Accept the change only when all in-scope scenarios have traceable cases, all required cases are implemented and executed, P0/P1 cases are neither skipped nor expected failures, later-layer requirements pass, and the SPEC, design, tasks, tests, and implementation agree.

If implementation changes a requirement, scenario, contract, or boundary, revise and review the matrix before continuing. Do not silently invent missing cases during implementation.
