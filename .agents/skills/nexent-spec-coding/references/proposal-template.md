# Proposal Template

## Usage guide

Create or update `proposal.md` according to [SPEC maintenance guidance](spec-maintenance-guide.md). Keep this fixed filename inside a SPEC directory whose name uses a registered level-1 module, an optional registered level-2 module, and a 2-to-5-word feature description. All three feature documents are required in this Nexent workflow; keep small changes concise. Required sections must remain. Include conditional sections whenever their stated condition applies. Optional sections may be removed. Replace placeholders and remove this guide from the generated document.

| Section | Requirement | When / what to write |
| --- | --- | --- |
| Why | Required | Confirmed problem and motivation |
| What Changes | Required | Outcomes and scope of the change |
| Capabilities and Scenarios | Required | Canonical SPEC name, level-1 module, optional level-2 module, stable feature IDs, document mode, baseline links and in-scope behavior scenarios |
| Baseline Inventory | Conditional | Reconstructing a missing or materially incomplete owning-feature SPEC |
| Acceptance Criteria | Required | Stable AC IDs, observable outcomes, proof method and pass conditions |
| Impact | Required | Affected modules, interfaces and dependencies |
| Non-Goals | Optional | Exclusions needed to prevent scope ambiguity |
| Behavior Details | Conditional | Flows or state transitions too complex to express clearly in individual ACs |
| Breaking Changes | Conditional | Any incompatible behavior, contract, data or configuration change |
| Open Questions | Optional | Unresolved questions; material questions block approval/implementation |

This is a Nexent adaptation of [OpenSpec's spec-driven schema](https://github.com/Fission-AI/OpenSpec/blob/main/schemas/spec-driven/schema.yaml). Baseline behavioral requirements normally live here; preserve existing spec.md documents. In delta mode, proposed requirement text lives in delta-spec.md and ACs reference it. Use `design.md` for implementation choices and `task.md` for execution and evidence. Do not claim OpenSpec CLI compatibility.

# Proposal — <Feature Name>

## Why

<Confirmed current behavior, its problem and why the change is needed. Cite existing documents or observations.>

## What Changes

<Specific additions, modifications or removals and intended outcomes. Define scope once. Mark incompatible changes BREAKING and explain them below.>

## Capabilities and Scenarios

<Record the canonical SPEC name, selected level-1 module, optional level-2 module or its omission reason, change type, document mode, baseline path/section IDs, revision or dated snapshot, status and search scope. Give each in-scope requirement a stable feature ID such as `[AUTH-001]` and list its observable Scenarios. Preserve existing IDs where available. List new/modified capabilities or preserved refactor behavior. Reference any delta requirement targets. These feature IDs and Scenarios are the source inventory for design.md's D1 case matrix. Do not invent behavioral changes.>

## Baseline Inventory

<Conditional when reconstructing a missing/incomplete SPEC. Describe the whole owning feature, its purpose, boundaries, main capabilities and unchanged end-to-end paths. Cite code/test evidence and distinguish observations, confirmed requirements and inferences. Most uncertain peripheral detail may be omitted. Separate observed defects and the intended fix; resolve material uncertainty. Baseline inventory does not imply all paths were runtime-verified.>

## Acceptance Criteria

### AC-001 — <Observable outcome>

- Given <precondition>
- When <action>
- Then <observable result>
- Verification <unit, API, browser, internal integration or real-model runtime as applicable>
- Evidence and pass condition <required artifact and exact assertion or threshold>

<Define current-change ACs and justified regressions; reference stable requirement feature IDs and baseline/delta requirements. Preserve historical ACs without claiming they were rerun. Add stable AC IDs as needed. Cover relevant negative, boundary, failure, permission and compatibility cases. Unchanged behavior can be a regression criterion. Avoid subjective pass conditions.>

## Impact

<Affected modules, APIs, consumers, services and dependencies. State compatibility constraints and whether new dependencies are needed. Technical details belong in design.md.>

## Non-Goals

<Optional. Scope exclusions that readers could otherwise misunderstand.>

## Behavior Details

<Conditional. Describe complex flows and state transitions; reference AC IDs without duplicating their definitions.>

## Breaking Changes

<Conditional. Identify incompatible changes, affected consumers and expected replacement behavior. Reference the migration approach in design.md.>

## Open Questions

<Optional. State each unresolved question and its effect on scope or acceptance. Resolve material questions before approval and implementation. Move resolved answers into the relevant section.>
