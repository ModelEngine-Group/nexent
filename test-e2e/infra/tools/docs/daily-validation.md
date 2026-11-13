# Daily validation scope

Strict `validate_test_assets.py --phase implementation` remains the developer gate.
It fails on every finding. Daily uses `--daily-report <outside-checkout>/asset-validation.json`
instead of `--generate`; it never rewrites repository assets or silently shrinks the plan.

## Decisions

- Unknown findings, malformed contracts/configuration, duplicate IDs and unsafe
  script paths stop the batch. Unsafe recovery journals, active owners/locks and
  pending D5 fault recovery also stop before synchronization. An ordinary failed
  deployment can use the validated Daily redeployment path described below.
- Explicit `CASE_EXECUTION_MISSING`, `CASE_SCRIPT_MISSING`,
  `CASE_SELECTOR_MISSING` and `CASE_PREPARATION_MISSING` findings with a known owner retain that Case in the plan
  and produce a BLOCKED receipt without starting its worker.
- Missing traditional UT references and stale derived reading views are metadata
  warnings, not proof that formal Cases cannot run. Authoritative assets still pass
  all other validation. Daily never claims UT execution from reference validation.
- `FEATURE_RESPONSIBILITY_UNRESOLVED` and known-Case
  `CASE_RESPONSIBILITY_UNRESOLVED` are metadata warnings for missing or ambiguous
  routing. Workers still execute, including the unassigned Cases; preserve their
  UNASSIGNED/AMBIGUOUS attribution and never guess a person. A planned Feature with
  no Cases is also a warning. Strict developer design/implementation validation
  still rejects every unresolved route. Missing or malformed shared routing
  configuration, invalid domain references, placeholder contacts and invalid
  patterns remain fatal; unknown Case scopes are never downgraded.
- `CASE_ID_FORMAT_INVALID` on a known Case is a metadata warning. The existing
  ID, stage, binding and declared status remain unchanged, including Cases already
  blocked for another reason. Strict design/implementation validation still rejects
  nonstandard new IDs. Daily never renames Cases or extends the frozen legacy list.
  Duplicate IDs, directory/ID mismatch, schema-invalid IDs or stages, script path
  escape and unreadable/modified naming catalogs remain fatal. An embedded ID stage
  contradicting the declared stage is a separate contract conflict, not this format
  warning.
- Shared missing helpers are inspected for every referring Case. Runtime preparation
  dependency failures retain the existing BLOCKED_BY_DEPENDENCY behavior; no
  dependency edges are inferred from titles, Change membership or failure keywords.

The launcher, full-registry selector, worker selection and deployment campaign use
the same typed policy. The global environment/configuration doctor, clean-source
and fingerprint gates remain required. Daily recovery is verified before business
Cases can start.

## Retrying a failed deployment

The scheduled `daily-launch.py` holds the test-home Daily lock and checkout
deployment lock before touching configuration or synchronizing develop. A pending
ordinary mode-switch journal does not by itself prevent fetching a repair. The
launcher validates the complete backup index and checksums, exact owned paths,
Local baseline, previous owner exit and absence of unrelated configuration edits.
Legacy journals require a terminal prior-batch receipt. It saves the old journal
and current configuration privately under `runtime/daily-recovery/`, then restores
only the four owned configuration files. Prior reports, original backups and
business data/volumes remain intact.

The old journal remains pending through synchronization, asset validation and
doctor. A new deployment campaign then adopts responsibility with its own backup
and pending journal. It builds/deploys the latest synchronized revision, requires
preflight and runtime-mode verification, and executes the configured Local recovery
selection before starting ordinary Cases. Final Local restoration and recovery
must pass before clearing that campaign's unchanged journal. Any failure retains
recoverable evidence; a later Daily can try again after its owner exits.

Targeted runs and resume do not gain this permission. A D5 fault journal or active
fault-operation lock, an active deployment owner, damaged/missing backups, path
redirection, changed unrelated configuration, dirty/divergent source or missing
explicit deployment hooks still stop execution. No marker is deleted merely to
let a launch proceed. These offline framework checks do not certify a live redeploy:

```text
python -m pytest -p no:nexent_formal_pytest test-e2e/infra/tools/tests/test_daily_recovery.py
```

Default implementation validation checks explicit preparation on every active
D2-D5 binding; no per-Case opt-in flag is needed. A self-contained proof declares
empty families after dependency/cleanup analysis. Daily suppresses the worker only
for a Case missing that declaration; invalid declarations/configuration remain
fatal. Developer strict validation rejects both types of finding before delivery.

## Accounting

`asset-validation.json` is saved with the launch and execution batch, including
campaign profiles. Summary exposes `asset_validation` and `coverage_integrity`.
A warning-only run may have every Case PASS and `execution_complete=true`, but its
overall status is FAILED and coverage integrity is INCOMPLETE. BLOCKED Cases stay
in the denominator and have acceptance_status=INCOMPLETE. No historical result is
rewritten. D6 and the sanitized publication bundle retain the validation receipt.

## Terminal reports and notifications

Daily sends a terminal report when a run succeeds, fails or is interrupted. A
failed recovery probe must not suppress notification. The report states the
execution status, saved reason, result counts and recovery state, distinguishing
restored configuration from a passed Local recovery probe. Missing recovery
evidence is reported as unverified, never as a healthy environment. Partial runs
retain `NOT_EXECUTED` and the original nonzero exit status.

The launcher also covers synchronization, asset-validation and doctor failures
before a batch exists, plus catchable interruption/SIGTERM. Once the executor
creates a batch, an explicit callback records its directory in the launch receipt;
the launcher uses that batch's notification receipt rather than an unrelated
`repository-latest.json`. This prevents duplicate launch/batch messages. If the
detailed report could not be rendered, the notification uses saved terminal
metadata and labels the missing details explicitly.

`notification-report.md` is the notification payload; original report and result
evidence remain local and unchanged by sending. Known environment credentials are
redacted from the payload. `notification.json` records `SENDING`, `SENT`,
`UNKNOWN` or `NOT_CONFIGURED`. Concurrent sends use a per-record lock; existing
or corrupt receipts are never blindly retried. Transport timeout or uncertainty
does not change the test outcome. Explicit `notify: false` remains respected.
Missing/invalid pipeline configuration does not prevent an alert if an existing
notification destination and CLI can still be loaded from machine-local env.

Only complete, safely restored campaigns may update the formal shared latest
report. Notification of an incomplete run does not replace that report or imply
all tests passed. SIGKILL, host power loss and unavailable credentials/transport
cannot guarantee delivery from the terminated process; no external watchdog or
automatic resend is introduced here.

This framework-only change is covered by offline notification, launcher,
orchestration, recovery and publication UT. It changes no product behavior or
formal D1-D5 acceptance contract, so no product UT or formal Case is added just
for a stage quota. Tests substitute message sending, deployment and remote Git;
local process/Git mechanics use isolated temporary fixtures.

```text
python -m pytest -p no:nexent_formal_pytest test-e2e/infra/tools/tests/test_terminal_notifications.py
```

Offline checks:

```text
python -m pytest -p no:nexent_formal_pytest test-e2e/infra/tools/tests/test_daily_validation.py
```

The formal pytest plugin is disabled only for framework UT so they do not require
machine-local business credentials. It remains enabled for actual formal Cases.
