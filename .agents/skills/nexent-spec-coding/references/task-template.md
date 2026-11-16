# Task Template

## Usage guide

Create or update task.md according to [SPEC maintenance guidance](spec-maintenance-guide.md). Preserve the existing filename, task IDs and factual execution records. A task document is an executable work plan: constraints, task list, per-task test work and implementation, actual test execution, and acceptance tracking.

## Writing guidance

- Keep the task list and task details consistent. Each task has a concrete outcome, affected ACs, dependencies and current status. Group related tasks without removing the per-task execution steps.
- For behavior changes, make test-first work explicit: add, strengthen or demonstrate adequate existing unit/regression tests before implementing the change, and run them first where they can expose the missing behavior. Formal case design precedes product implementation; fixed formal scripts follow stable interfaces under the guides below. Reuse sufficient tests rather than requiring new tests for every task.
- Distinguish test design, executable test files and test execution. A verification step must identify the tests to run and the expected assertions; document review, schema validation, file presence or a statement that behavior is correct does not replace running required tests.
- Link the proposal, design and overall user flow instead of repeating them. Use current code and test paths when known; explicitly mark proposed files, and do not invent selectors, commands that supposedly ran, or passing results.
- Keep unfinished work unchecked. Use pending, in progress or blocked in the task list, and explain blockers briefly. Check completion only after the task's implementation and required verification are complete. Adapt inapplicable steps with a reason; do not copy obsolete constraints or historical results into the current plan.

## Required references

The following requirements still apply in full; the template shows where to plan and record the work rather than repeating their detailed rules:

- [Skill workflow](../SKILL.md#gated-workflow): lifecycle, validation and delivery requirements.
- [Test design guide](test-design-guide.md): test responsibilities and case design.
- [Test implementation guide](../../nexent-test-assets/references/test-implementation.md): scripts, bindings, preparation and cleanup.
- [Verification guide](verification-guide.md): execution, evidence, result status and closeout.

# Tasks — <Feature Name>

<Reference proposal.md and design.md, identify the target repository and current baseline, and state what this plan covers. Remove template instructions from the output.>

## Implementation constraints

<List the constraints that affect this change's implementation, such as scope, preserved behavior, permission/data boundaries and interface compatibility. Reference the owning design or repository rule rather than copying general policy. Keep these visible before the task list.>

## Task list

| ID | Outcome | ACs | Dependencies | Status |
| --- | --- | --- | --- | --- |
| TASK-001 | <Concrete implementation outcome> | AC-001 | <Task IDs or none> | Pending |
| TASK-002 | <Necessary integration / delivery outcome> | <AC IDs> | TASK-001 | Pending |

## Task details

### TASK-001 — <Concrete implementation outcome>

**Goal / ACs:** <Observable outcome and affected AC IDs; link the relevant design section.>

**Dependencies:** <Prerequisite task IDs and any required inputs. For cross-layer work, identify the frontend/backend handoff.>

**Affected files:** <Known product paths and test paths; label proposed files as new.>

**Test-first work**

- [ ] 001.1 <Add, strengthen or reuse specific tests for the affected behavior; state the input, expected result and relevant forbidden side effects. Complete the applicable formal case design under the guides.>
- [ ] 001.2 <Run the relevant tests before implementation where applicable; record the actual baseline and the behavior failure they detect, or why existing passing tests are sufficient.>

**Implementation**

- [ ] 001.3 <Implement the change needed to meet the agreed behavior and tests, preserving the stated constraints.>
- [ ] 001.4 <Once affected interfaces are stable, implement or reuse the required formal test scripts and bindings, plus affected documentation, under the guides.>

**Targeted verification**

- [ ] 001.5 <Run the relevant test files/selectors or registered Cases after implementation, check actual assertions and record results. Add the applicable product checks separately; do not substitute them for test execution.>

<Give the actual runnable command when the test path is known. During planning, identify the intended test file / scenario and mark the final command as pending if necessary. For example, replace the placeholder before executing:>

```text
python -m pytest <actual-test-file> -q
```

**Completion:** <The requested behavior is implemented and the task's required tests pass; link actual execution evidence and record remaining blockers. Marking product code complete alone does not complete the task or its ACs.>

<Repeat this structure for actual tasks. Use integration tasks for checks spanning several tasks; do not defer every task's tests to the final task. A test-only or documentation-only task omits inapplicable product work without inventing work to fill the template.>

## Acceptance traceability

<List every current AC and link its implementation tasks and verification. Do not duplicate detailed case steps.>

| AC | Related tasks / design | Traditional UT | Formal Case IDs | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| AC-001 | TASK-001 / <design section> | <Test references> | <Case IDs> | PENDING | <Actual results / evidence links> |

Use PENDING, PASS, FAIL or BLOCKED under the verification guide. Keep UT and formal results separate. A task checkbox or passing document validator does not establish acceptance.

## Execution notes

<Record actual commands, tested revision/profile, results and evidence links under the verification guide. Separate a pre-implementation baseline from post-implementation verification. Keep failed evidence and link reruns; do not paste raw logs.>

| Task | Command / test selection | Tested revision / profile | Result | Evidence / blocker |
| --- | --- | --- | --- | --- |
| TASK-001 | <Actual command once executed> | <Actual revision / profile> | PENDING | <Evidence link or blocker> |

## Completion check

- [ ] Implementation constraints and required task work are satisfied; relevant test files/Cases were executed and actual results recorded.
- [ ] Every current AC has the required passing verification and linked evidence; unresolved failures or blockers remain explicit.
- [ ] Required closeout checks are complete, documents agree with implementation and test assets, and remaining risks are stated.
