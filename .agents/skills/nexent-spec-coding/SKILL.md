---
name: nexent-spec-coding
description: Run document-driven SPEC development for Nexent features, fixes, refactors, APIs, UI, internal logic, and model or Agent runtime changes. Use with the Git-managed nexent code repository and its separate sibling nexent-doc repository when work requires reviewed requirements, test-first implementation, functional verification, and acceptance evidence.
---

# Nexent SPEC Coding

Develop Nexent from an approved SPEC and produce evidence for every acceptance criterion.

## Repository boundaries

- Treat `nexent/` as the Git-managed code repository and its sibling `nexent-doc/` as the document repository.
- Never run Git commands in the document repository or move SPEC documents into the code repository.
- Search and reuse existing feature specifications before creating a new one. Name each new SPEC or change directory from the canonical registry at `<document-repository>/docs/Developing/spec-module-abbreviations.md`: `<level-1>-<level-2>-<2-to-5-feature-words>`, or `<level-1>-<2-to-5-feature-words>` when level 2 is omitted. Keep `proposal.md`, `design.md`, `task.md`, and `delta-spec.md` as fixed artifact names inside that directory.
- Preserve unrelated changes. Record the initial code branch/status, applicable repository instructions, build configuration, and test layout.

## Read the right references

Select the document mode with [spec-maintenance-guide.md](references/spec-maintenance-guide.md): create a requirement-scoped SPEC for new features and refactors; update a usable baseline or add a delta for a bug fix; reconstruct the owning feature from code and tests when no usable baseline exists. Omit uncertain peripheral detail, but resolve uncertainty that affects the change.

| Work | Required reference |
| --- | --- |
| Name a new SPEC or change set | Canonical module registry at `<document-repository>/docs/Developing/spec-module-abbreviations.md` |
| Create or revise `proposal.md` | [proposal-template.md](references/proposal-template.md) |
| Create or revise `design.md`; design D1 cases | [design-template.md](references/design-template.md) and [test-design-guide.md](references/test-design-guide.md) |
| Create or revise `task.md` | [task-template.md](references/task-template.md) |
| Plan, execute, or close verification | [verification-guide.md](references/verification-guide.md) |

`proposal.md` owns current-change AC definitions, `design.md` owns design rationale and test design, and `task.md` owns the single traceability/evidence table. A delta owns proposed requirement text when delta mode is selected. Preserve established baseline requirements, historical ACs, and approved decisions. Follow each template's required, conditional, and optional sections; remove unused optional sections and placeholders.

This workflow adapts [OpenSpec](https://github.com/Fission-AI/OpenSpec/blob/main/schemas/spec-driven/schema.yaml) to Nexent. It uses singular `task.md`, local document paths, and manual baseline/delta integration; it does not claim OpenSpec CLI compatibility.

## Gated workflow

### 1. Analyze

Search existing SPECs and choose the document mode before writing. For a new SPEC or change set, resolve its owning level-1 module and use a registered level-2 module when the scope has one stable owner; then choose a 2-to-5-word feature description. Inspect the relevant code, callers, interfaces, persistence, services, UI, tests, configuration, and runtime paths. Cite concrete paths, symbols, APIs, schemas, and configuration names. Do not implement production code during analysis.

### 2. Write and review the SPEC

Create or update `proposal.md` and `design.md`, then `task.md`. Define stable requirement feature IDs and observable ACs with verification layers, evidence, and exact pass conditions. For an undocumented bug, reconstruct the owning feature's main behavior and design while keeping implementation scope limited to the requested fix.

In `design.md`, map every in-scope Scenario and relevant unit-level design contract to stable D1 case IDs at the lowest proving layer: `FE-COMP`, `BE-UT`, or `SDK-UT`. Define implementable preconditions, steps, assertions, forbidden side effects, priority, fixtures/mocks, and later verification exclusions. Build the `task.md` traceability table from requirements, ACs, design sections, D1 cases, later verification, and planned evidence.

Review the documents, any delta, baseline references, and actual code together. The design gate fails if a Scenario lacks a D1 case, a case lacks implementable assertions, a case crosses its declared boundary, or the matrix is stale. Resolve questions that change scope, behavior, design, tests, or tasks. Production implementation starts only after explicit approval; explicit autonomous authorization may be recorded with a self-review in `task.md`.

### 3. Write D1 tests first

Implement the designed tests before the corresponding production behavior and bind each test to its case ID. Use fixed fixtures and mocks only for isolation or controlled faults. For a bug, preserve a focused reproduction that fails before the fix when feasible. Run the smallest relevant group and confirm the expected failure before production edits when a meaningful red step is possible; otherwise record the concrete reason in `task.md`.

Missing, unimplemented, skipped, or expected-failure cases do not pass. Keep product, test, and environment failures distinguishable.

### 4. Implement and pass D1

Implement the minimum approved production change needed to satisfy the cases, following existing architecture and contracts. Each feature task names its AC and case IDs and completes only after all associated assertions, including forbidden side effects, pass.

Run the smallest group while developing, then the complete affected D1 group. Do not weaken assertions to pass. When implementation changes a requirement, Scenario, contract, boundary, or design, update and re-review the documents and matrix before continuing.

### 5. Verify changed behavior

After required D1 cases pass, execute every later verification layer triggered by the change. Use a real browser for frontend interaction, a running service and real requests for HTTP contracts, stable-interface tests for internal behavior, and actual Nexent paths plus configured services and Langfuse evidence for model, embedding, or Agent runtime behavior.

Source review, mocks, builds, and D1 results do not replace required functional verification. Missing required credentials, infrastructure, or evidence makes the affected AC `BLOCKED`. Follow the verification guide for secret handling, proof details, and statuses.

### 6. Close out

Update `task.md` with actual code paths, case results, commands/scenarios, artifacts, trace references, and approved deviations. Use `PASS` only after all required proofs pass; use `PENDING`, `FAIL`, `BLOCKED`, and justified layer-level `N/A` as defined by the verification guide.

Confirm the SPEC, delta, design, tasks, tests, and implementation agree. Integrate approved and verified deltas into the baseline, preserve delta history, and resolve concurrent baseline changes. Report changed files, AC results, executed checks, remaining risks, and unverified items. Completion requires every current required AC to be `PASS`.

## Stop conditions

Pause the affected work when approval is missing, a material requirement conflict remains unresolved, required access or evidence is unavailable, verification would mutate a system outside the authorized scope, or an AC cannot be proved with the available surface. Explain the affected ACs and missing input, and continue safe independent work when the blocker is local.
