# Configuration lifespan formal-test repair

> Historical initial repair and execution record. The user subsequently approved
> forced-process restart as sufficient startup-failure recovery. AC-04's original
> same-process cleanup requirement and the instruction below to retain its FAIL
> are superseded by `CONFIG-FORCED-RESTART-ACCEPTANCE-20261022.yaml` and the adjacent
> verification document. The original 10 PASS / 3 FAIL receipt is not rewritten.

## Scope and baseline

- Change: `CONFIG-LIFESPAN-TEST-FIX-20261022`.
- Feature: `V5-REL-AUTO-AF6CA560E762D682`; Case: `REL-AUTO-AF6CA560E762D682`.
- Product version: `ed373b9f0c33b6505ead5f6f77aa35138ad85699` on `djb/bugfix-test-case`.
- Original failure reproduced through `run_cases.py`: `AUTOMATION_ERROR` at the
  deleted `sync_system_default_prompt_template` replacement. Evidence batch:
  `runs/repository-local/20261022T064215271516Z-REL-AUTO-AF6CA560E762D682`.
- Product commit `6735e06b7` (#4134) retired private Prompt Template startup
  synchronization. It updated traditional UT and formal imports but left this
  Case's old failure-tolerance contract and replacements unchanged.
- This is a test-only repair. Product source, machine-local configuration,
  historical Daily results, workflow and notification behavior are unchanged.

## Existing proof and missing proof

| Existing proof | Boundary / gap | Decision |
| --- | --- | --- |
| `test/backend/app/test_config_app.py::TestConfigAppRouterConfiguration::test_config_app_registers_api_key_routes` checks current configuration validation and successful startup wiring. | UT uses an isolated module and substitute manager; it does not establish real worker shutdown or startup-failure resource recovery. | Reuse as traditional UT, do not register as a formal Case. |
| Original D5 script checks startup/shutdown order and healthy responses using `_FakeManager`. | Deleted prompt symbols prevent execution; failure cases never assert manager/default cleanup. | Strengthen the same D5 Case; add no D1 or new Case ID. |
| Reporting uses an explicit Feature override to scheduled tasks. | This Case owns configuration-service lifecycle, not user automation scheduling. | Change this one override to system management (`@武兆福`) and add a routing regression. |

## Acceptance assertion review

All selectors below belong to the Case-local `test.py`. The real product lifespan,
recovery orchestration, `ThreadManager`, default-manager registry and health route
execute. Only persistence/recovery operations, evaluation/Dreaming background
services and Workbench backfill are replaced; their calls are observed without
starting real tasks. AIDP checks use synthetic, nonfunctional configuration.

| AC | Actual selector and variants | Assertions / evidence |
| --- | --- | --- |
| AC-01 | `test_startup_order_and_conditional_backfill` (Workbench off/on) | Exact startup sequence, one control-io recovery with real `ManagedTaskSpec` metadata, real running state and default registration; conditional backfill. |
| AC-02 | `test_external_configuration_validation` (disabled/configured/missing-url/missing-key) | Current validation executes, rejects missing enabled configuration, propagates RuntimeError and prevents Dreaming/service entry; valid configuration enters service. |
| AC-03 | `test_readiness_created_running_stuck_and_closed` | Actual ASGI health endpoint returns 503/200/503/503 with exact manager/stuck fields; only the stuck snapshot is fault-injected. |
| AC-04 | `test_startup_failure_releases_resources` (recovery/upload/configuration) | Original errors propagate, later work does not start, health is observed before cleanup, and `_assert_released` requires closed state, zero active/stuck tasks, cleared default and bounded worker exit. No xfail, skip or `raising=False`. |
| AC-05 | `test_shutdown_order_and_body_error_propagation` (normal/body-error) | Exact single stop/stop/shutdown/clear sequence, configured shutdown budget, body error propagation and actual resource release. |
| AC-06 | `test_shutdown_error_still_clears_default` | Inject an error after actual manager shutdown; require error propagation and the default-registration finally block. This does not claim scheduler-stop failures are covered. |
| AC-07 | All six named selectors above | Fixture records `product_before_test_cleanup` separately from `test_safety_cleanup`, asserts no sensitive marker in call/setup logs, no surviving owned threads and restoration of the previous default manager. Whole-scenario mapping remains failed when a product assertion fails. |

The observed executor shutdown uses `wait=False`; workers may consume their stop
sentinel just after shutdown returns. The test permits bounded natural thread exit
(up to 2 seconds, never longer than the configured grace), without adding product
cleanup. A `running` manager or uncleared default fails immediately. The fixture's
own cleanup uses the original shutdown method and cannot turn that failure green.

## Verification and product finding

- Baseline reproduction: 1 automation error at the retired symbol.
- Formal repaired Case: 13 collected variants, 10 PASS, 3 FAIL, zero errors/skips
  in the final complete repaired run. Evidence batch:
  `runs/repository-local/20261022T065546834402Z-REL-AUTO-AF6CA560E762D682`.
- AC-01/02/03/05/06 passed. AC-04 failed; AC-07's all-scenario execution mapping
  also failed because it includes those failed members. No mapped selector is
  missing. Semantic review remains `UNREVIEWED` in the machine receipt; this document
  records concrete assertion review, not automatic semantic certification.
- All 13 scenario evidence files report no sensitive marker leakage. Test safety
  cleanup closes the owned manager, clears its registration and leaves no owned
  worker. The failed product state is retained separately.
- Product finding: startup recovery, upload cleanup or AIDP validation exceptions
  occur before the product `try/finally` protecting `yield`. The manager remains
  `running`, its default registration remains installed, and lifecycle shutdown is
  not called. This is a real in-process resource ownership gap, not proof that a
  normally started HTTP server accepted traffic after failed startup.
  All three controlled failure observations also show the in-process readiness
  route returning HTTP 200 with `manager_state=running` before test safety cleanup.
- Keep the formal Case `active` and its result FAIL. Do not weaken or remove
  AC-04 to satisfy the current product. Fixing production lifecycle rollback needs
  separately authorized product work and a corresponding bugfix record.
- Related traditional UT: 73 PASS (`test/backend/app/test_config_app.py`).
- Reporting infrastructure tests: 12 PASS (`test_report_ownership.py`), including
  the new exact Feature routing check.
- Design/implementation strict acceptance validation and generated views pass.
  Regenerated registry/Excel are derived, ignored assets, not manually edited.

## Commands

Use the machine-local test Python environment; keep outputs under `<test-home>`.

```text
python test-e2e/infra/tools/validate_test_assets.py --phase design --generate --require-acceptance-case REL-AUTO-AF6CA560E762D682
python test-e2e/infra/tools/validate_test_assets.py --phase implementation --generate --require-acceptance-case REL-AUTO-AF6CA560E762D682
python test-e2e/infra/tools/run_cases.py REL-AUTO-AF6CA560E762D682 --test-home <test-home>
python -m pytest test/backend/app/test_config_app.py -q --disable-warnings
python -m unittest discover -s test-e2e/infra/tools/tests -p test_report_ownership.py -v
python scripts/check_copyright.py test-e2e/cases/REL-AUTO-AF6CA560E762D682/test.py test-e2e/infra/tools/tests/test_report_ownership.py
git diff --check
```
