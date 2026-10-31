# Design Template

## Usage guide

Create or update `design.md` according to [SPEC maintenance guidance](spec-maintenance-guide.md). Reference `proposal.md` for motivation, scope and acceptance criteria. Define formal D1-D5 case contracts before product implementation; implement fixed automation after stable interfaces exist. Use [D1-D5 test design guidance](test-design-guide.md) and the `nexent-test-assets` skill. Structured test assets, not this prose or Excel, are the executable source of truth.

For a bug with no usable SPEC, use [bugfix-design-template.md](bugfix-design-template.md), which shares the association matrix below. For an existing SPEC, retain its matrix and add only relevant updates. A matrix inventories coverage; it does not require every listed Case to change or run in the current change.

## Writing guidance

- Explain the overall approach before component, API or data details. For multi-step user journeys or frontend/backend coordination, include an overall interaction diagram, preferably a Mermaid flowchart or sequence diagram. Connect the user's entry action, frontend feedback, backend processing and relevant dependencies to the final visible outcome; identify responsibility and state changes at each boundary. Simple changes do not require a diagram, and no fixed diagram type or count applies.
- Keep the main path readable and show behavior-changing branches: for example, required user input or confirmation, failure, cancellation, or resuming after a manual step, where applicable. State when control passes back to the user and how the flow continues or ends. Reference detailed contracts and proposal scenarios rather than listing every request field or repeating every branch in prose.
- Separate the current baseline from the proposed change. Summarize what is reused, modified or added once; distinguish code observations, agreed requirements and unverified assumptions. Link detailed evidence instead of repeating investigation notes throughout the design.
- Explain significant current decisions with their context, chosen approach, rationale and consequences. Discuss realistic alternatives only where they help explain the current choice. Replace or remove outdated decisions and update their references; do not keep superseded versions, abandoned proposals or change histories in the current design by default.
- Expand only the technical detail needed to implement the affected behavior. Cover relevant interfaces, data, states, failures, permissions and compatibility together at their owning boundary. Examples clarify a contract; code paths locate an implementation. Neither replaces the explanation, and pseudocode is optional.
- Reference proposal requirements and AC IDs instead of restating the motivation or full business rules. Define each contract in one place and link from other sections. Keep evidence sufficient for engineering decisions without reproducing raw logs or a line-by-line code walkthrough.
- Scale sections to the change. Omit inapplicable interface, migration or model-runtime sections; retain applicable test responsibilities below. Put planned proof and its boundaries here, and actual commands, results and evidence links in task.md. Do not claim a runtime result from static inspection or unit tests.

# Design — <Feature Name>

## Context

<Give only the current behavior and constraints needed to understand the change. Identify the dated/revisioned baseline and summarize reused, modified and new parts; reference proposal.md for motivation, scope and ACs.>

## Proposed Design

<Start with the overall approach. For multi-step user journeys or frontend/backend coordination, add an overall interaction diagram from the user's entry action to the visible outcome, including relevant handoffs, state changes and behavior-changing branches. Then explain affected component responsibilities and the necessary interfaces/data and failure handling. Distinguish retained behavior from changes. Put each detailed contract in one place; link conditional sections below when they own that detail.>

## Decisions

### D-001 — <Significant decision>

<Explain the current choice, context, rationale, meaningful alternatives and consequences; link relevant ACs. Include only decisions that need explanation. Update replaced decisions in place and remove obsolete text and references.>

## Traditional UT + D1-D5 Test Responsibilities

<List Feature IDs, business rules and known coverage for the defined functional scope. Link Case IDs and the behavior proved at each stage. Notes distinguish reuse, strengthen, add, regression-only and unaffected Cases, with impact reasons. Put complete executable case fields in structured test assets. N/A means irrelevant; GAP means relevant but uncovered; UNKNOWN means the baseline/association is unavailable. GAP/UNKNOWN are document annotations, not Case IDs. Distinguish coverage inventory from the current execution selection; do not fill five columns by inventing new Cases. Include profiles where applicable.>

| Feature / rule / AC | Traditional UT | D1 | D2 | D3 | D4 | D5 | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <ID> | <unit behavior + reuse/strengthen/add> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <case IDs or N/A> | <distinct proof boundary / profile / exclusion reason> |

<Assess UT for every product change. Do not require all stages or edits to both suites. UT remains outside the formal registry. Preserve existing D1; new D1 proves component collaboration beyond UT, D3 proves actual runtime integration. State real versus substituted dependencies. A unit-only AC can be proved by UT; higher-boundary ACs require their selected formal evidence.>

<Before adding D1, read existing UT/formal assertions and record their actual proof, the remaining gap, real internal collaboration, controlled boundaries and why D2/D3 is not the intended surface. A Feature with no D1 is valid; do not duplicate unit tests to fill this matrix. For code already developed, use the test-backfill route and record current proof gaps, not fictional earlier design/execution.>

## Test Implementation Strategy

<Describe traditional UT success/error/boundary/regression obligations and applicable formal scripts separately. UT selectors are confirmed after implementation; formal scripts/bindings follow stable interfaces except focused bug reproduction. For each changed formal acceptance obligation, explain actual tests/assertions and collection/execution checks, not just file/ID existence. State relevant local UT commands and affected Case execution. Existing D1 stays; completeness gaps are reported separately from script PASS.>

## Risks / Trade-offs

<State known implementation, testing or operational risks and mitigations.>

## Interface / Data Changes

<Conditional. Describe signatures, requests/responses, events, schemas, configuration, validation and compatibility.>

## Migration / Rollback

<Conditional. Describe deployment order, migration, compatibility, rollback and irreversible limits.>

## Model / Agent Verification

<Conditional. Identify actual runtime paths, logical provider profiles, deterministic scenarios, downstream assertions and trace evidence. Never record secret values.>

## Open Questions

<Optional. Resolve questions that change behavior, scope or task breakdown before implementation.>
