# Config forced-restart acceptance revision

## Authorized contract

The user explicitly accepts recovery through forced restart. This is an authorized
acceptance change, not an automatic adjustment to match the implementation.
Startup failure must remain visible and must not enter service. An old process
may require forced termination; after the injected fault is withdrawn, a fresh
process must actually serve healthy traffic. Automatic restart and same-process
manager cleanup are not required for AC-04. Normal/body-error shutdown obligations
remain strict and unchanged.

This record supersedes only the earlier startup-failure cleanup requirement in
`CONFIG-LIFESPAN-TEST-FIX-20261022`. Keep its original execution evidence intact.
There is no product-code, existing-service, machine-configuration or notification
change.

## Prior actual-deployment evidence

Ubuntu probes reused the deployed immutable image, actual start-backend script,
Config service entry point and Docker `always` policy. Config service, manager,
maintenance-loop and startup-script hashes matched the current Windows sources.
All probes had no network, existing business volumes or host ports; SQL startup
migrations were intentionally disabled and persistence operations controlled.

- Recovery failure: exit code 3; Docker automatically restarted once and the
  replacement returned ready=200 after withdrawal of the injected fault.
- Upload-cleanup/configuration failure: the real non-daemon maintenance thread
  held the interpreter in thread shutdown for more than 65 seconds. No automatic
  restart occurred. Both recovered after explicit forced restart with the fault
  withdrawn. This finding remains an engineering observation, not a failed AC-04
  under the newly authorized criterion.
- A permanent missing AIDP configuration is not expected to heal merely by
  restarting. Withdrawal/correction of the startup fault is explicit.

Machine-local diagnostic roots are `runs/diagnostics/config-startup-20261022*`
and `runs/diagnostics/config-startup-long-20261022*`; historical results remain
separate from the new formal execution.

## Formal implementation and assertion review

Case: `REL-AUTO-AF6CA560E762D682`; Feature:
`V5-REL-AUTO-AF6CA560E762D682`. No new Case or D1 is added.

- `test_startup_failure_recovers_after_process_restart[recovery/upload/configuration]`
  starts the Case-local `startup_probe.py` with the selected test interpreter.
  The worker executes actual Config lifespan, Uvicorn, manager and maintenance
  thread. Only persistence, Dreaming side effects and Workbench are controlled.
- Bind only dynamic loopback ports. Existing containers/services are not touched.
- Require the declared RuntimeError and original error text, no service-entry or
  Dreaming event, and no HTTP 200 readiness from the failed process. Record its
  actual manager/default/thread state without making those states fail AC-04.
- Terminate the exact owned process if necessary and wait for its exit, with a
  ten-second bound. Record natural versus forced termination and its exit code.
- Start a separate healthy worker after withdrawing the injected fault; require a
  different PID, initially CREATED manager and empty process-default registration.
  A successful recovery needs actual HTTP 200, manager_state=running and zero stuck
  count within 45 seconds, followed by a second healthy observation while alive.
  Killing the old worker alone cannot pass this assertion.
- Always terminate/wait for all owned child processes, including failed attempts.
  Save sanitized subprocess logs, startup events, exit classifications, old/new
  identities and HTTP results through the existing case-evidence writer.
- AC-01/02/03/05/06 retain the existing in-process startup, configuration, health
  and strict normal/body-error shutdown assertions. AC-07 maps all actual tests;
  recovered-process evidence is distinct from final test safety cleanup.
- This fixed formal test proves process-level recovery; the earlier Ubuntu Docker
  evidence separately proves the deployment/container behavior. It does not
  claim every local run starts a real Docker deployment or validates live DB work.

## Execution

- Final targeted Windows formal run: 13 collected variants, **13 PASS**, zero
  failures, errors or skips; 56.30 seconds. The preceding 58.25-second run also
  passed all 13 before a diagnostic-only change to preserve sanitized leak evidence.
- Final evidence: `runs/repository-local/20261022T075602851418Z-REL-AUTO-AF6CA560E762D682`.
- Three `runtime/*-process-restart-*.json` files retain actual failed-process
  observations, final process cleanup and replacement health responses.
- Existing earlier receipt remains 10 PASS / 3 FAIL against its previous contract.
- Formal acceptance execution is checked separately from semantic review; a
  generated mapping is not automatic correctness certification.
- Final observed replacement readiness times: recovery 8.062 seconds, upload
  7.578 seconds, configuration 7.719 seconds. Recovery exited naturally; the latter
  two were forcibly terminated. All replacement PIDs differed from their failed
  predecessors, all six owned processes exited, and no sensitive marker was logged.
- AC-01 through AC-07 report PASS with no missing tests; the machine receipt
  retains semantic_review=UNREVIEWED rather than self-certifying semantic review.
- Related ownership/navigation infrastructure regressions: 26 PASS. Copyright
  and Python compilation checks pass; product/deployment directories have no diff.

Use the normal repository validator with
`--require-acceptance-case REL-AUTO-AF6CA560E762D682` and the targeted
`run_cases.py` entry point with a machine-local test home. No dependency install,
Daily rerun, shared report publication or Feishu message is required.
