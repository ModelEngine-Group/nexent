---
name: nexent-spec-coding
description: Run the Nexent requirement or bug lifecycle from SPEC analysis through feature catalog and D1-D5 case design, product implementation, fixed test implementation, local verification, and delivery evidence. Use for features, fixes, refactors, APIs, UI, and model or Agent runtime changes.
---

# Nexent SPEC Coding

Develop Nexent from an evidence-backed SPEC while keeping product behavior, formal D1-D5 test assets, implementation, and verification synchronized.

## Repository boundaries

- Treat `nexent/` as the Git-managed product repository and its sibling `nexent-doc/` as the document repository.
- Never run Git commands in the document repository or move SPEC documents into the product repository.
- Preserve unrelated changes. Record the initial branch/status, applicable repository instructions, build configuration, and test layout.
- Keep the existing tests under `test/backend`, `test/sdk`, and `test/ext_components` as Legacy UT. Do not map them into the formal D1-D5 manifest.

## Read the right references

| Work | Required reference |
| --- | --- |
| Choose the SPEC maintenance mode | [spec-maintenance-guide.md](references/spec-maintenance-guide.md) |
| Create or revise `proposal.md` | [proposal-template.md](references/proposal-template.md) |
| Create or revise `design.md`; design formal D1-D5 cases | [design-template.md](references/design-template.md) and [test-design-guide.md](references/test-design-guide.md) |
| Create or revise `task.md` | [task-template.md](references/task-template.md) |
| Plan, execute, or close verification | [verification-guide.md](references/verification-guide.md) |

Use `nexent-test-assets` for the concrete feature-catalog, case, automation, manifest, schema, and Excel formats. `proposal.md` owns the current-change acceptance criteria, `design.md` owns design rationale and test strategy, and `task.md` owns the change-level traceability and evidence record.

## Gated workflow

### 1. Analyze

Search existing SPECs and choose the maintenance mode. Inspect the relevant code, callers, interfaces, persistence, services, UI, formal test assets, configuration, and runtime paths. Cite concrete paths, symbols, APIs, schemas, and configuration names. Do not implement production code during analysis.

### 2. Define behavior and formal D1-D5 cases

Create or update `proposal.md`, `design.md`, and `task.md`. Update the product feature catalog and define observable acceptance criteria. Design every applicable D1-D5 case before product implementation. Each case must have a stable Case ID, owning Feature ID, priority, precise preconditions, steps, expected results, forbidden side effects, and the stage-specific fields required by the repository schemas.

Create a requirement change record under `test/changes/requirements/` or a lightweight bug record under `test/changes/bugs/`. Run the formal asset validators and regenerate the Excel view. Do not invent final script paths, selectors, implementation hashes, or passing results during design.

The design gate fails when an in-scope behavior lacks an applicable case or justified exclusion, a case lacks executable assertions, stage boundaries are violated, affected Feature/Case declarations are stale, or schema and traceability validation fail. Resolve material behavior conflicts before implementation. No separate manual test-case approval is required by this workflow.

### 3. Implement the product behavior

Implement the minimum change needed to satisfy the defined behavior, following existing architecture and contracts. If implementation reveals that a requirement, product rule, Scenario, or test contract is wrong, update and validate the formal design assets before continuing. Do not silently weaken a case to fit the implementation.

### 4. Implement fixed tests and the manifest

After product implementation, implement the affected formal D1-D5 scripts under `test/automation/d1` through `test/automation/d5`. Bind each automated script or test item to its Case ID and incrementally update only the affected entries in `test/manifests/d1-d5.yaml`. Then run full manifest and traceability validation.

For a confirmed bug, a focused failing reproduction may be implemented before the product fix when that is the clearest way to preserve the regression. Existing formal cases should be strengthened instead of duplicated when they already own the behavior.

Legacy UT maintenance remains separate and uses `nexent-python-tests` only when the change breaks or intentionally updates that suite.

### 5. Verify affected behavior

Run the affected formal D1-D5 cases selected from the change record. Use fixed Playwright scripts for D4. Keep Mock and Real Smoke results distinct when both profiles apply. Missing, unimplemented, skipped, or expected-failure required cases do not pass. Keep product, test, environment, and external-provider failures distinguishable.

Record sanitized commands, results, evidence paths, and unresolved blockers in `task.md`. Do not claim API, browser, model, Agent, security, reliability, performance, or deployment acceptance from a lower layer.

### 6. Close out

Run the unified formal-asset validator, deterministic Excel check, affected tests, and relevant product checks. Confirm SPEC, feature catalog, cases, change record, scripts, manifest, implementation, and evidence agree. Report changed files, Case results, remaining risks, and unverified items. Formal completion requires every current required acceptance criterion to pass.

## Stop conditions

Pause the affected work when a material behavior conflict remains unresolved, required access or evidence is unavailable, verification would mutate a system outside the authorized scope, or an acceptance criterion cannot be proved with the available surface. Continue safe independent work when the blocker is local.
