# Design Template

## Usage guide

Create or update `design.md` according to [SPEC maintenance guidance](spec-maintenance-guide.md). Keep this fixed filename inside a SPEC directory whose name uses a registered level-1 module, an optional registered level-2 module, and a 2-to-5-word feature description. This document is required for Nexent; a small fix with an adequate baseline may use short paragraphs. For an undocumented bug, reconstruct the overall owning-feature design, including unaffected main paths. Omit most unconfirmed peripheral details, not evidence-backed core structure. Required sections must remain. Conditional sections become mandatory when triggered. Delete unused optional/conditional sections, placeholders and this guide from the generated document.

| Section | Requirement | When / what to write |
| --- | --- | --- |
| Context | Required | Relevant code and constraints; whole-feature reconstruction when no usable baseline exists |
| Decisions | Required | Chosen approach and reasons; real alternatives when a meaningful choice exists |
| Proposed Design | Required | Target flow and component responsibilities |
| D1 Test Design | Required | Scenario-level FE-COMP, BE-UT and SDK-UT cases before implementation |
| Later-layer Verification Strategy | Required | API, browser, real-model, Agent-runtime and other applicable proof surfaces |
| Risks / Trade-offs | Required | Known risks and mitigations, or a brief no-known-material-risk statement |
| Interface / Data Changes | Conditional | Changed interfaces, schemas or persistent state |
| Migration / Rollback | Conditional | Data/config migration, deployment transition or compatibility work |
| Model / Agent Verification | Conditional | Model inference, embedding, Agent runtime or tool-flow changes |
| Detailed File List / Diagrams | Optional | Extra detail that clarifies implementation |
| Open Questions | Optional | Only questions that can safely be deferred |

Reference `proposal.md` for motivation, scope and AC definitions. Follow [D1 test design guidance](test-design-guide.md) for the mandatory case matrices and test-first gate. Keep the single change-level acceptance traceability table in `task.md`. Use this template's guidance rather than reproducing every example. The approach follows [OpenSpec's design guidance](https://github.com/Fission-AI/OpenSpec/blob/main/schemas/spec-driven/schema.yaml), with Nexent-specific mandatory design and verification sections.

# Design — <Feature Name>

## Context

<Relevant current flow, reusable components and constraints. Cite concrete paths, symbols, APIs, schemas or configuration names. Reference proposal.md. For new code, identify existing integration boundaries.>

## Decisions

### D-001 — <Decision>

<Chosen approach, rationale and related AC IDs. Explain meaningful alternatives and trade-offs where they exist; do not invent alternatives for a straightforward fix. Add design-level boundaries only when needed.>

## Proposed Design

<For a missing baseline, first document the whole feature's evidence-backed current design, component responsibilities, core flows, interfaces/data and failure behavior. Separate observations and uncertainty from intended requirements; do not invent historical decision rationale. Then identify this fix's target design. For an existing baseline, preserve unaffected design and describe target control/data flow, affected component responsibilities and relevant failure handling. Link to ACs. Focus on architecture and approach rather than line-by-line implementation.>

## D1 Test Design

<List every in-scope Requirement feature ID and Scenario. State D1 scope and explicit exclusions. Map each independently verifiable behavior to at least one stable case ID at the lowest proving layer. Use separate tables for applicable FE-COMP, BE-UT and SDK-UT cases with the complete field set from test-design-guide.md: Case ID, Feature ID, Level-1 module, Level-2 module, Responsibility, Title, Layer, Priority, Scenario-based, Journey, Preconditions, Local assets/config, Steps, Expected results/assertions and External dependency policy. Use `-` when level 2 is omitted. Include forbidden-side-effect assertions where relevant. State recommended test-file grouping and the test-first flow: implement tests, observe the expected failure when feasible, implement production behavior, run the smallest case group, then run the complete affected D1 group. Record a concrete reason in task.md when a meaningful red step cannot be produced. Human review must confirm that every case actually proves its Scenario.>

## Later-layer Verification Strategy

<Map AC IDs and D1 exclusions to required API, browser, internal integration, migration, real-model, embedding, Agent-runtime, security, reliability or other system proof. State scenarios, environment/data, assertions and required evidence. Explain why any normally relevant layer is N/A. These checks run only after required D1 cases pass, except diagnostic execution. D1 success does not prove these layers. Detailed execution tasks and results belong in task.md. Follow verification-guide.md.>

## Risks / Trade-offs

<Known implementation or operational risks and their mitigations. If none are material, state that briefly with the basis for that assessment.>

## Interface / Data Changes

<Conditional. Document changed signatures, requests/responses, events, tool contracts, configuration or schemas. Explain validation, error behavior and compatibility as applicable.>

## Migration / Rollback

<Conditional. Deployment order, migration steps, existing consumer/data compatibility, rollback procedure and any irreversible limits.>

## Model / Agent Verification

<Conditional. Identify the actual Nexent runtime path, applicable model/embedding environment variable names, deterministic scenarios, downstream assertions and required Langfuse spans/generations. Include prompts/context, tool arguments/results and final-output checks as relevant. Never record secret values. Mark the affected AC BLOCKED when required service access or trace evidence is missing.>

## Detailed File List / Diagrams

<Optional. Planned files and responsibility changes or a diagram that adds information. Avoid line numbers.>

## Open Questions

<Optional. Only unknowns that do not change behavior, the chosen approach or task breakdown may remain. Resolve material questions before finalizing tasks or starting implementation. Fold answers into the formal design.>

