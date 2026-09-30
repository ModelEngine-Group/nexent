# SPEC Creation and Maintenance

## Choose the document mode

Read this guide before selecting document paths or writing a SPEC. Search the resolved document repository by capability, entry points, API names and related code/tests. Read candidate documents and follow their references before concluding that a baseline is missing. Record the search scope and selected baseline in proposal.md, or in the lightweight bugfix design.md.

Here, a full Nexent SPEC is the feature's proposal.md, design.md and task.md document set. A baseline describes the established feature; a change records proposed work. A delta records requirement changes against a named baseline. Preserve an existing repository's spec.md files and naming conventions; do not force a format migration.

| Work | Required document action |
| --- | --- |
| New feature | Create a requirement-scoped SPEC document set. Reference related existing capabilities; create a new baseline only for genuinely new capability scope. |
| Refactor | Create a requirement-scoped change SPEC with design, preserved behavior and regression ACs. Reuse existing baseline requirements. If external behavior is unchanged, do not invent behavioral deltas. |
| Bug fix with usable baseline | Follow the existing SPEC's Feature/business-rule/Case relationships, confirm code impact, and update relevant sections only. Preserve unaffected contracts and historical evidence. Add a delta only when a requirement actually changes and that mode is useful. |
| Bug fix without usable baseline | Create a lightweight design.md using [the bugfix template](bugfix-design-template.md). Define the coherent capability's final behavior and Feature/Case coverage, then identify this fix's changes and verification. A proposal/task document set is not required. |

If existing documents cover part of the owning feature, reuse relevant sections and add only the context needed to understand this fix; missing peripheral documentation is separate maintenance work. If a fix restores an already specified contract, retain that contract and add/update its regression scenario and design evidence as needed; a behavioral MODIFIED block is unnecessary unless the documented requirement actually changes.

## Paths and sources of truth

Preserve historical document paths. Name every new full SPEC directory under `<document-repository>/docs/Developing/` as `<level-1>-<level-2>-<feature-words>`, or `<level-1>-<feature-words>` when level 2 is omitted. Select the level-1 module from `<document-repository>/docs/Developing/spec-module-abbreviations.md`. Use a registered level-2 module when the scope has one stable owner; omit it when the change spans multiple capabilities within the level-1 module or has no stable level-2 owner. Use 2 to 5 lowercase, hyphen-separated English words for the feature description. For a cross-module change, select the module that owns the externally observable contract and list other affected modules in proposal.md. Add a missing module to the canonical registry before using it. Do not invent a local module name.

When a separate change set is needed, name its directory with the same rule under the owning SPEC's `changes/` directory. Requirement change sets contain `proposal.md`, `design.md`, `task.md`, and, only when requirements change, `delta-spec.md`. A new lightweight bugfix directory contains only `design.md`, follows the same registered module/directory naming rule, and lives under `<document-repository>/docs/Developing/` when no owning SPEC exists. Preserve existing paths and link to the product repository's bug Change ID. Do not invent a separate document root for test assets. These are Nexent conventions, not OpenSpec CLI paths. Never run Git in the document repository.

Choose direct update or delta for each affected requirement; avoid maintaining two independent proposed versions. Record baseline path, relevant section/requirement IDs, baseline revision or dated content snapshot, chosen mode and change status in proposal.md or the lightweight bugfix design.md. Dates/snapshots must not imply a Git repository. Each delta must identify the baseline it modifies; preserve existing names and IDs. For multiple baselines, group operations by explicit target rather than mixing ambiguous requirement names.

The baseline remains the reference for established behavior until an approved change is integrated. Direct edits must clearly mark proposed versus established content and preserve prior relevant content. In delta mode, proposed requirement text lives in delta-spec.md, proposal.md contains intent and ACs that reference it, design.md explains implementation, and task.md owns execution evidence. Do not duplicate full requirement definitions across those files.

## Define an undocumented bug's functional boundary

Use a lightweight design when no usable SPEC exists. Describe the complete coherent capability that owns the bug: its purpose, entry points, inputs/outputs, main flow, rules and directly related failure boundaries in the final state. This should be broader than the changed lines or one failing branch, but need not reconstruct the whole module or product. Inspect callers, relevant code, formal Feature/Case assets and existing tests as evidence.

| Content | Requirement |
| --- | --- |
| Feature purpose, functional boundary and final normal behavior | Required in design.md, including retained main paths within that boundary |
| Overall component responsibilities, key flow, interfaces/data and relevant failure behavior | Required in design.md to the extent supported by evidence |
| Evidence paths/symbols/tests and observation date or code revision | Required for documented behavior claims |
| This bug's reproduction, observed defect, expected correction and regression ACs | Required, clearly separated from the functional coverage inventory |
| Feature/business-rule to D1-D5 Case matrix | Use the same columns as the requirement design template; link existing IDs and distinguish changed, regression-only and unaffected coverage |
| Unrelated coverage gaps or unavailable test baseline | Record as limitations/deferred work; they do not automatically become this fix's acceptance criteria |
| Uncertain peripheral details, exhaustive branches, historical rationale, diagrams | Optional; omit most unconfirmed detail rather than inventing it |
| Uncertainty affecting the fix's behavior, design or acceptance | Must be resolved before implementation; cannot be omitted as peripheral |

Distinguish observed implementation, test-backed behavior, confirmed intended behavior and unverified inference. Code demonstrates what currently happens; it does not by itself prove the intended requirement. Cross-check bug expectations with existing tests, callers, docs and user requirements. Never promote the observed defect to intended behavior. Do not invent historical motivations or claim exhaustive certainty.

Keep the capability definition and final design in design.md, with a separate current-fix scope and Acceptance Traceability table. Documenting retained behavior does not require creating, modifying or executing every Case listed in the coverage matrix. Reuse existing Cases, strengthen confirmed gaps and add only required regression coverage. Full historical SPEC reconstruction is separate work when requested.

## Delta document usage guide

Use this structure only when the chosen mode requires a delta against an existing baseline. Delete unused operation sections. Without an existing SPEC, use the lightweight bugfix design rather than an unanchored delta. Keep behavioral requirements distinct from implementation instructions.

| Content | Requirement |
| --- | --- |
| Baseline target, revision/snapshot, requirement IDs and change status | Required |
| At least one applicable operation below | Required for a behavioral delta; omit the delta if none apply |
| ADDED Requirements | Conditional on a new requirement |
| MODIFIED Requirements | Conditional on changing an existing requirement; include the full updated requirement and all retained scenarios |
| REMOVED Requirements | Conditional on removal; include reason and migration or an explicit no-migration explanation |
| RENAMED Requirements | Conditional on name-only changes; provide exact old/new names; also use MODIFIED under the new name if content changes |
| Supporting notes | Optional; design detail belongs in design.md |

Use `## ADDED Requirements`, `## MODIFIED Requirements`, `## REMOVED Requirements` and `## RENAMED Requirements` for operation groups. Define requirement blocks with `### Requirement: <existing or new name>` and observable SHALL/MUST statements. Each added/modified requirement has at least one `#### Scenario: <name>` with WHEN/THEN and optional GIVEN. Retain all unaffected scenarios when replacing a requirement. A short description of changed lines is not a complete MODIFIED block. Renames use FROM/TO mappings. Preserve these structural tokens if writing Chinese content.

For this Nexent adaptation, a delta targets an existing feature baseline. New requirements without a baseline use the full SPEC path above; bugs without a baseline use the lightweight design path. Existing native OpenSpec layouts may use their own new-capability delta convention.

## Review and integrate

Before approval, check the canonical SPEC name, registered level-1 module, optional level-2 selection, selected mode, baseline coverage, operation targets, unchanged requirements and AC links. Define acceptance for the current change plus justified regression coverage. Baseline inventory entries are not automatically new ACs; if an existing AC is in scope, its required verification still applies. Never erase old ACs or evidence to narrow the current task.

At closeout, verify current-fix ACs and justified regressions, and review the updated documentation against evidence. For deltas, integrate verified requirement changes into the baseline and record the target/status in task.md or the lightweight design. Preserve historical acceptance and evidence without treating all historical ACs as this fix's execution scope. Recheck concurrent baseline changes without overwriting unrelated work.

## Official references and local extensions

OpenSpec distinguishes [current specs and change deltas](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md). Its [spec-driven schema](https://github.com/Fission-AI/OpenSpec/blob/main/schemas/spec-driven/schema.yaml) defines operation blocks, complete modified requirements and observable scenarios. Full requirement SPECs and lightweight bugfix designs are Nexent conventions. They do not imply OpenSpec CLI compatibility or automatic archival.
