# Task Template

## Usage guide

Create or update task.md according to [SPEC maintenance guidance](spec-maintenance-guide.md). Preserve the existing filename and task IDs. This template describes how to organize tasks; it does not replace or relax the project's testing and delivery requirements.

## Writing guidance

- **Split the work:** Group related tasks by the result they deliver. Each task should be small enough to judge as complete on its own. Do not create a task per file or copy a fixed set of phases into every change.
- **Cover the necessary work:** Include applicable test design, product implementation, test implementation and execution. They may be organized by deliverable or by phase; follow the required order in the guides below.
- **State dependencies:** Name prerequisite task IDs where order matters. For frontend/backend work, reference the overall flow in design.md and identify the handoffs needed to complete it.
- **Define completion:** Say what will change and how completion will be checked. Include the tests and documentation required for that work under the guides below; use separate tasks for checks that span several deliverables. Reference requirements and design instead of repeating them.
- **Show current status:** Use numbered checkboxes. Keep pending, in-progress and blocked tasks unchecked, with a short status or blocker note when useful. Check a task only after its completion conditions are met.
- **Keep the plan current:** Update remaining tasks as facts change. Record actual results and link supporting evidence; do not invent passing results or paste raw logs.

## Required references

Apply the relevant requirements when planning tasks, setting completion conditions and recording results. These remain mandatory where applicable; they are referenced here rather than repeated:

- [Skill workflow](../SKILL.md#gated-workflow): lifecycle, required validation and delivery steps.
- [Test design guide](test-design-guide.md): test responsibilities and case design.
- [Test implementation guide](../../nexent-test-assets/references/test-implementation.md): executable tests, bindings, preparation and cleanup.
- [Verification guide](verification-guide.md): execution, acceptance traceability, evidence, result status and closeout.

# Tasks — <Feature Name>

<Reference the proposal and design. Briefly state what this plan covers. The groups below illustrate implementation and testing work, not mandatory phases. Remove template instructions and adapt groups to the actual work.>

## 1. <Deliverable>

Dependencies: <None, or prerequisite task IDs. Add a task-specific dependency to that task when needed.>

- [ ] 1.1 <Define or confirm the tests needed for this deliverable>; complete when <the affected ACs have clear test expectations and identified existing coverage or gaps>. [Requirement / design reference]
- [ ] 1.2 <Implement the product change>; depends on <task ID>; complete when <the intended behavior and its required unit checks are satisfied>.
- [ ] 1.3 <Implement or reuse the required tests>; depends on <task ID>; complete when <the applicable test scenarios are executable>.
- [ ] 1.4 <Run the deliverable's checks>; depends on <task IDs>; complete when <actual results and evidence are recorded against the affected ACs>.

## 2. <Another deliverable or necessary integration work>

Dependencies: <Prerequisite task IDs.>

- [ ] 2.1 <Complete another deliverable or check the integrated flow>; complete when <the intended result is demonstrated and recorded>.

## Acceptance traceability

<List every AC in the current change. Link to tasks and tests instead of repeating the requirement or test steps. One AC may need several tests, and one test may cover several ACs.>

| AC | Related tasks / design | Unit verification | Formal Case IDs | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| AC-001 | <task IDs / design section> | <test reference> | <Case IDs> | PENDING | <actual results / evidence links> |

Keep task completion separate from acceptance results. Use PENDING, PASS, FAIL or BLOCKED according to the verification guide; record inapplicable verification with its reason. Do not fill planned work with assumed results.

## Completion check

- [ ] Required implementation and testing tasks are complete, with actual results recorded.
- [ ] Every current AC has the required passing verification and linked evidence under the verification guide.
- [ ] Required closeout checks are complete, documents agree with the implementation, and remaining risks are stated.

## Status notes

<Optional. Briefly note progress or blockers by task ID. Keep required execution details in the linked evidence according to the verification guide, without duplicating logs.>
