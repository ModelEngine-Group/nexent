# Formal test-asset lifecycle

## Requirement

1. Update the owning Feature and business rules.
2. Create the requirement change record under `test-e2e/changes/requirements/`, listing added, modified, and retired Feature and Case IDs.
3. Assess traditional UT and every applicable D1-D5 boundary. Record reuse/strengthen/add and justified exclusions in the SPEC test-responsibility matrix; UT remains outside the formal registry. No per-stage quota or mandatory edits to both suites apply.
4. Run the design-phase unified validator and regenerate the Excel view.
5. Implement product code and applicable traditional UT with nexent-python-tests; keep unit and formal acceptance obligations distinct.
6. Implement each affected primary script beside its Case and add or update that Case's `execution.yaml`; run the implementation-phase unified validator.
7. Run relevant traditional UT and affected D1-D5 Cases locally; record results separately outside the design assets. For new/acceptance-modified Cases, follow acceptance-integrity.md. Preserve existing D1 and mark unreviewed completeness honestly.

Do not invent script paths, selectors, hashes, or results during design.

For every new/current product Change, add traditional_ut with decision (reuse/strengthen/add/exempt), behavior intentions and rationale; confirm actual repository test_selectors after implementation. Use --require-ut-change <Change-ID> in both validator phases. Existing historical Changes need no bulk rewrite. Exemption applies only to justified non-behavior changes, not unavailable environments. This record is traceability, not UT execution or formal Case registration.

## Bug

Follow [bugfix.md](bugfix.md). With a usable SPEC, follow and confirm its Feature/rule/Case associations. Without one, use `nexent-spec-coding`'s lightweight design.md, defining the coherent capability and the same D1-D5 matrix without requiring a proposal/task set. Record a bug Change under `test-e2e/changes/bugs/`, with impact evidence and selected Cases. Reuse or strengthen existing coverage first; zero additions is valid. Record no gap or an unavailable baseline accurately rather than claiming coverage is absent. Update Feature/Case contracts only when changed or missing; historical coverage gaps are separate work.

## Change record paths

| Change type | Required directory |
| --- | --- |
| `requirement` | `test-e2e/changes/requirements/` |
| `bugfix` | `test-e2e/changes/bugs/` |
| `refactor` | `test-e2e/changes/refactors/` |
| `test-fix` | `test-e2e/changes/test-fixes/` |

Use one change record per file. Files directly below `test-e2e/changes/` are invalid.

## Daily ownership

The product repository owns formal assets. Ubuntu Daily consumes the `develop` versions and never rewrites them. Daily may report drift or missing assets, but fixes return through the product-repository workflow.

PR CI continues the traditional UT set; Daily executes formal D0-D6. Do not add independent CI, modify GitHub required checks, deploy, notify or switch the operational Daily merely to maintain these rules. Each machine supplies its own test-home configuration and assets; tests and bindings come from the locked product version.
