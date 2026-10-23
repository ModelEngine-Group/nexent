---
name: nexent-test-assets
description: Create and maintain Nexent's requirement-driven feature catalog, D1-D5 structured cases, change records, fixed automation, implementation manifest, generated Excel baseline, migration inventory, and Mock/Real execution declarations. Use for requirements, bug regressions, test implementation, V5 migration, or formal test-asset consistency work. Excludes the Legacy UT suite.
---

# Nexent formal test assets

Maintain one traceable chain:

`Requirement or Bug -> Feature -> D1-D5 Case -> Manifest -> Fixed Script -> Result`.

Paths are relative to the repository root. The structured YAML/JSON files are authoritative; `test/generated/Nexent_测试基线.xlsx` is a deterministic read-only view.

## Boundaries

- Do not reuse or register tests from `test/backend`, `test/sdk`, or `test/ext_components` as formal D1 cases. Those are Legacy UT.
- Formal scripts live only below `test/automation/d1` through `test/automation/d5`.
- Design cases before product implementation. Implement fixed scripts and manifest entries after product implementation, except an intentional bug reproduction may be written earlier.
- Update only affected manifest entries, then validate the whole manifest.
- Do not edit the generated Excel workbook directly.
- Do not encode secrets, personal absolute paths, or environment-specific runtime IDs in formal cases or scripts.
- Business tests must not depend on a specific SQL file path. Test migration behavior only at the D5 deployment boundary.
- Store change records by type: requirements in `test/changes/requirements/`, bug fixes in `test/changes/bugs/`, refactors in `test/changes/refactors/`, and test-only fixes in `test/changes/test-fixes/`. Do not place change files directly below `test/changes/`.

## Select a mode

| Mode | Use | Required reference |
| --- | --- | --- |
| `requirement-design` | Add or change product behavior and design D1-D5 cases | [lifecycle.md](references/lifecycle.md), [case-design.md](references/case-design.md) |
| `bugfix` | Record a defect, explain the escaped gap, and add/reuse/strengthen regression coverage | [lifecycle.md](references/lifecycle.md), [bugfix.md](references/bugfix.md) |
| `test-implementation` | Implement fixed scripts and incrementally update the manifest | [test-implementation.md](references/test-implementation.md), [manifest.md](references/manifest.md) |
| `migration` | Convert V5, fixed scripts, manifest, and referenced assets without changing behavior | [migration.md](references/migration.md) |
| `mock-migration` | Add Mock/Real profiles after migration equivalence passes | [mock-profiles.md](references/mock-profiles.md) |

Read only the references needed for the selected mode.

## Required workflow

1. Inspect the owning Feature, existing formal Cases, change record, manifest entries, scripts, and repository status.
2. Modify the authoritative YAML/JSON before regenerating derived views.
3. Preserve stable Feature and Case IDs. Retire instead of deleting historical contracts.
4. During requirement design, run `python test/tools/validate_test_assets.py --phase design --generate-excel`.
5. After fixed scripts and manifest entries exist, run `python test/tools/validate_test_assets.py --phase implementation --generate-excel`. Use `python test/tools/generate_excel.py --check` for a read-only Excel drift check.
6. In implementation mode, run the affected selectors and report exact results. A schema-valid asset is not execution evidence.

## Status rules

- `active`: required and executable according to its automation field.
- `blocked`: required but missing a declared prerequisite; never count as pass.
- `manual`: intentionally manual and not represented as automated.
- `skipped_by_policy`: excluded by an explicit current product-test policy.
- `retired`: historical behavior no longer executed.

A2A is in scope across D1-D5, including fixed D4 journeys. OAuth and CAS journeys remain `skipped_by_policy` until their policy changes.

## Generated Excel layout

Generate exactly seven sheets: `00_说明`, `01_功能清单`, and `02_D1` through `06_D5`. Each D1-D5 row includes its requirement and business-rule traceability, automation status, framework, script, selector, execution profile, Mock services, logical assets, and readable manifest validation status. Keep contract and implementation hashes in hidden trailing columns. Do not create separate automation or coverage sheets.
