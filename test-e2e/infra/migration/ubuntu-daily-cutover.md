# Ubuntu repository Daily cutover

Repository assets are authoritative. Daily never analyzes Diff to author Cases,
calls OpenCode, overlays candidates, or promotes test code. Developer changes
must be committed and pushed before the executor can fetch them.

## Entry

Use the dedicated test-home Python. The wrapper accepts the checkout, test home,
and branch as positional arguments; add `--execute` for actual synchronization,
build, deployment and full execution. Without it, the command only prints a plan.

```bash
bash test-e2e/infra/scripts/daily-launch.sh REPO TEST_HOME djb/test-baseline --execute
```

During integration the checkout must already be on `djb/test-baseline`. For
production explicitly switch a clean checkout to `develop` and change the
scheduler's branch argument. Do not silently switch branches on each invocation.

One lock covers synchronization through D6. Dirty, divergent, locally ahead,
or wrong-branch checkouts fail closed. Only fast-forward updates are accepted.
The launcher imports the updated runner after synchronization and executes it
under the held lock rather than acquiring the same lock again.

Deterministic generated views are refreshed before execution, and tracked
navigation drift blocks execution. Static assets use the catalog provisioner;
previously provisioned, unmodified fixtures are backed up and updated by hash;
an unknown or user-modified fixture is not overwritten. Resolve differing files using
the catalog and preserve a local backup before retrying. No user configuration,
secret or runtime ID is copied from Git.

## Machine setup and acceptance

1. Verify no old batch or recovery guard is active. Preserve existing config,
   scheduler definitions and historical results before changes.
2. Fetch the committed integration branch, prepare the existing dedicated Python,
   Node 22, browser and locked toolchains. Non-interactive PATH must expose Node.
3. Reuse machine-local `config/pipeline.yaml` build/deploy/preflight commands.
   They must not call the old Daily maintenance pipeline or recursively launch Daily.
4. Keep notification disabled for acceptance. Run doctor and selected online Cases
   before a full D1-D5 acceptance batch. Product failures remain failures.
5. Verify terminal accounting, cleanup, failure evidence, D6 and report parity.
   Unknown owners remain unassigned; no speculative responsibility assignment.
6. Only then replace the old scheduler command, disable old notification delivery
   and explicitly enable the new notification after validating its destination.

Results remain in test-home `runs/repository-daily/`; launcher failures go into
`runs/daily-launch/`. `reports/repository-latest.json` locates the latest batch.
Incomplete batches never send normal notifications. No GitHub artifacts or
workflow modifications are required for this cutover.

Rollback changes the scheduler back to its backed-up command. Retain the new
results for diagnosis; do not automatically revive old asset-generation tasks.
