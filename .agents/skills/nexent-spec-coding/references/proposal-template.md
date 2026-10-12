# Proposal Template

## Usage guide

Use this template for a full requirement SPEC or when an existing proposal needs a relevant update. Keep this fixed filename inside a SPEC directory whose name uses a registered level-1 module, an optional registered level-2 module, and a 2-to-5-word feature description. Bugs without a usable SPEC use [the lightweight design template](bugfix-design-template.md); no proposal/task set is required. Preserve the required sections when this template applies. Include conditional sections only when their condition applies. Replace placeholders and remove this guide from the generated document.

| Section | Requirement | When / what to write |
| --- | --- | --- |
| Why | Required | Confirmed problem and motivation |
| What Changes | Required | Outcomes and scope of the change |
| Capabilities and Scenarios | Required | Canonical SPEC name, level-1 module, optional level-2 module, stable feature IDs, document mode, baseline links and in-scope behavior scenarios |
| Baseline Inventory | Conditional | Explicit baseline documentation work or context required for this requirement change; not an automatic bugfix obligation |
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

<Record the canonical SPEC name, selected level-1 module, optional level-2 module or its omission reason, change type, document mode, baseline path/section IDs, revision or dated snapshot, status and search scope. Give each in-scope requirement a stable feature ID such as `[AUTH-001]` and list its observable Scenarios. Preserve existing IDs where available. List new/modified capabilities or preserved refactor behavior. Reference any delta requirement targets. These feature IDs and Scenarios are the source inventory for design.md's formal D1-D5 case contracts. Do not invent behavioral changes.>

## Baseline Inventory

<Conditional when baseline documentation is explicitly in scope. Describe the coherent capability, its purpose, boundaries, main capabilities and retained paths. Cite evidence and distinguish observations, confirmed requirements and inferences. Keep baseline context separate from current-change acceptance. Missing SPECs in bugfix mode use the lightweight design template instead.>

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
