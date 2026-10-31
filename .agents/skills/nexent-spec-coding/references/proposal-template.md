# Proposal Template

## Usage guide

Use for a full requirement SPEC or a relevant revision to an existing proposal. Preserve established paths, names and IDs. Follow [SPEC maintenance guidance](spec-maintenance-guide.md) for document mode and naming; use the lightweight bugfix template where applicable. Include conditional sections only when needed, and remove template instructions from the output.

A proposal supports agreement on the problem and expected change. It is not a technical design or an execution report. The Nexent adaptation keeps behavioral requirements and acceptance here; preserve existing spec.md documents and delta-mode ownership rather than duplicating requirements. It does not claim OpenSpec CLI compatibility.

## Writing guidance

- Write for readers who understand the product but may not know its internals. Use familiar product terms and concrete subjects and verbs. Explain necessary domain terms on first use; avoid replacing a straightforward problem with an abstract label.
- In **Why**, describe the current problem or opportunity and its impact. Use a short example when it makes the problem easier to understand. Do not add proposed algorithms, implementation alternatives or arguments for a preferred solution.
- In **What Changes**, describe the intended capabilities, behavior and scope. Describe user interactions where they clarify the requirement. Put internal APIs, data structures, tuning parameters, code paths and technical trade-offs in design.md unless they are explicit product requirements or externally imposed constraints.
- For a multi-step user journey, describe the entry point, user actions, system feedback and final outcome together in **Behavior Details**. Include relevant choices, required manual steps and how the user continues or stops; reference scenarios and ACs instead of duplicating them. Use a simple user-facing flow diagram when helpful; put the frontend/backend interaction diagram in design.md.
- Keep sentences focused on one idea and paragraphs on one topic. Use enough detail to make the requirement unambiguous; do not impose a fixed word count, page count or number of sentences. Use lists or tables for parallel items, not as a requirement to fragment ordinary prose.
- Distinguish existing behavior, requested behavior and unresolved assumptions. Cite supporting observations concisely; put investigation logs, detailed code inventories and test execution records in design.md or task.md. Do not repeat evidence disclaimers throughout the problem description.
- State each requirement fully in one place and reference its ID elsewhere. Keep examples subordinate to the rule, and do not turn an example into an additional requirement. Preserve substantive constraints while removing repetition.
- Define acceptance in terms of observable results and required limits. Keep stable IDs and a concise verification approach here; put test architecture, scripts, selectors, execution artifacts and results in design.md or task.md. Do not invent numerical targets merely to make prose sound measurable.

## Section responsibilities

| Section | Include when | Content |
| --- | --- | --- |
| Why | Required | Current problem or opportunity and its impact |
| What Changes | Required | Intended changes, outcomes and scope |
| Capabilities and Scenarios | Required | Stable capability/requirement IDs and observable scenarios |
| Baseline Inventory | Baseline documentation is requested or necessary | Relevant existing capabilities; link detailed implementation evidence |
| Acceptance Criteria | Required | Observable outcomes, pass conditions and verification approach |
| Impact | Required | Affected product areas, consumers, interfaces and dependencies |
| Non-Goals | Scope could otherwise be misunderstood | Relevant exclusions |
| Behavior Details | The interaction cannot be understood from scenarios and acceptance alone | User-visible flows and business rules; reference rather than repeat ACs |
| Breaking Changes | A change is incompatible | Affected consumers and expected replacement behavior |
| Open Questions | Material questions remain | The unresolved decision and its effect on scope or acceptance |

# Proposal — <Feature Name>

<Use a compact metadata block for the canonical SPEC name, registered module, document mode, baseline reference/revision or dated snapshot, and change status. Record the search scope once where baseline selection needs explanation. Do not expand metadata into repeated narrative.>

## Why

<Describe the current problem or opportunity and its impact. Add a concrete example or concise source reference when useful. Keep implementation analysis and proposed solutions in design.md.>

## What Changes

<Describe specific new, changed or removed behavior and the intended outcome. Define the scope once. Mark incompatible changes BREAKING.>

## Capabilities and Scenarios

<Preserve stable Feature/requirement IDs and Scenario IDs; assign new IDs only where needed. Describe the actor or trigger and observable behavior. Reference baseline or delta targets for modified requirements. Do not duplicate metadata or implementation plans.>

## Baseline Inventory

<Conditional. Summarize existing capabilities relevant to the change. Distinguish observed behavior from intended requirements. Reference detailed code evidence in design.md; do not copy a file-by-file audit here.>

## Acceptance Criteria

### AC-001 — <Observable outcome>

- Given <relevant precondition>
- When <action or trigger>
- Then <observable result and any required limit>
- Verification <concise proof method; link detailed verification design where needed>

<Preserve stable ACs and justified regressions. Include relevant failure, boundary, permission and compatibility behavior. Keep separate obligations distinct; do not pack unrelated requirements and their implementation rationale into one criterion. Execution evidence belongs in task.md.>

## Impact

<Identify affected product areas, interfaces, consumers and dependencies at the level needed to understand the change. Link design.md for implementation impact.>

## Non-Goals

<Optional. State only exclusions needed to clarify scope.>

## Behavior Details

<Conditional. For multi-step journeys, show how the user starts, what they do and see, and how the flow completes. Include relevant choices, manual steps and continuation or stopping points. A simple flow diagram is optional. Explain other necessary business rules here; reference scenarios and AC IDs without restating them. Keep internal call chains in design.md.>

## Breaking Changes

<Conditional. Describe incompatibility, affected consumers and replacement behavior. Reference migration details in design.md.>

## Open Questions

<Optional. Describe each unresolved decision and its effect. Resolve questions that change scope or acceptance before implementation; move resolved answers into the relevant section.>
