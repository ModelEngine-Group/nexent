---
name: nexent-test-assets
description: Create and maintain Nexent's repository-owned feature catalog, D1-D5 case-local contracts and fixed scripts, change records, generated execution registry and Excel view. Use for requirements, bug regressions, test implementation, and formal asset migration. Excludes Legacy UT.
---

# Nexent formal test assets

Maintain one traceable chain:

`Requirement or Bug -> Feature -> D1-D5 Case -> case-local execution.yaml -> Fixed Script -> Result`.

Paths are relative to the repository root. Authoritative assets live under `test-e2e/features/<Feature-ID>/feature.yaml`, `test-e2e/cases/<Case-ID>/case.yaml`, and `test-e2e/changes/<type>/`. Each implemented Case owns `execution.yaml` and its primary test script in the same Case directory. `features/<Feature-ID>/cases.md`, `test-e2e/infra/generated/registry.json`, and the Excel workbook there are generated read-only views; no hand-maintained central manifest or cross-platform symlink is needed.

## Boundaries

- Do not reuse or register tests from `test/backend`, `test/sdk`, or `test/ext_components` as formal D1 cases. Those are Legacy UT.
- A Case's primary script lives beside its `case.yaml`; shared framework helpers live under `test-e2e/infra/automation/`. Do not make a shared helper the primary Case binding.
- Design cases before product implementation. Implement fixed scripts and case-local `execution.yaml` after product implementation, except an intentional bug reproduction may be written earlier.
- Update only affected Case directories, then validate the complete derived registry.
- Do not edit the generated Excel workbook directly.
- Do not encode secrets, personal absolute paths, or environment-specific runtime IDs in formal cases or scripts.
- Business tests must not depend on a specific SQL file path. Test migration behavior only at the D5 deployment boundary.
- Store change records by type under `test-e2e/changes/{requirements,bugs,refactors,test-fixes}/`. Changes record affected IDs; the lasting Feature and Case definitions remain in their respective directories.

## Select a mode

| Mode | Use | Required reference |
| --- | --- | --- |
| `requirement-design` | Add or change product behavior and design D1-D5 cases | [lifecycle.md](references/lifecycle.md), [case-design.md](references/case-design.md) |
| `bugfix` | Record a defect, explain the escaped gap, and add/reuse/strengthen regression coverage | [lifecycle.md](references/lifecycle.md), [bugfix.md](references/bugfix.md) |
| `test-implementation` | Implement fixed scripts and case-local bindings | [test-implementation.md](references/test-implementation.md), [manifest.md](references/manifest.md) |
| `migration` | Convert V5, fixed scripts, execution bindings, and referenced assets without changing behavior | [migration.md](references/migration.md) |
| `runtime-migration` | Prepare and verify repository-owned local/Daily execution without switching the operational suite | [runtime-migration.md](references/runtime-migration.md) |
| `mock-migration` | Add Mock/Real profiles after migration equivalence passes | [mock-profiles.md](references/mock-profiles.md) |

Read only the references needed for the selected mode.

## Required workflow

1. Inspect the owning Feature, existing formal Cases, change record, execution bindings, scripts, and repository status.
2. Modify the authoritative YAML/JSON before regenerating derived views.
3. Preserve stable Feature and Case IDs. Retire instead of deleting historical contracts.
4. During requirement design, run `python test-e2e/infra/tools/validate_test_assets.py --phase design --generate`.
5. After fixed scripts and case-local bindings exist, run `python test-e2e/infra/tools/validate_test_assets.py --phase implementation --generate`; omit `--generate` for a read-only drift check.
6. Run affected selectors through `python test-e2e/infra/tools/run_cases.py <Case-ID> --test-home <machine-local-directory>` and report exact results. Static validation is not execution evidence.

## Status rules

- `active`: required and executable according to its automation field.
- `blocked`: required but missing a declared prerequisite; never count as pass.
- `manual`: intentionally manual and not represented as automated.
- `skipped_by_policy`: excluded by an explicit current product-test policy.
- `retired`: historical behavior no longer executed.

A2A is in scope across D1-D5, including fixed D4 journeys. OAuth and CAS journeys remain `skipped_by_policy` until their policy changes.

## Generated Excel layout

Generate exactly seven sheets: `00_说明`, `01_功能清单`, and `02_D1` through `06_D5`. Each D1-D5 row includes requirement and business-rule traceability, automation status, framework, script, selector, execution profile, Mock services, logical assets, and binding validation status. Keep contract and implementation hashes in hidden trailing columns. Do not create separate automation or coverage sheets.
