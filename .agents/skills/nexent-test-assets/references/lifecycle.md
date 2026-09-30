# Formal test-asset lifecycle

## Requirement

1. Update the owning Feature and business rules.
2. Create the requirement change record under `test-e2e/changes/requirements/`, listing added, modified, and retired Feature and Case IDs.
3. Design every applicable D1-D5 case and record justified stage exclusions.
4. Run the design-phase unified validator and regenerate the Excel view.
5. Implement product code.
6. Implement each affected primary script beside its Case and add or update that Case's `execution.yaml`; run the implementation-phase unified validator.
7. Run affected D1-D5 cases and record results outside the design assets.

Do not invent script paths, selectors, hashes, or results during design.

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
