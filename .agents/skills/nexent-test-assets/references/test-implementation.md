# Fixed test implementation

Implement only from an active or blocked formal Case. Choose the framework by proof boundary: pytest for Python unit, API, and runtime checks; the frontend component framework for FE-COMP; Playwright for D4; and an appropriate fixed runner for D5.

Preserve existing D1, including unit-oriented scripts. New D1 proves component contracts/internal collaboration, not merely another copy of traditional UT. D3 proves actual inter-component/service/protocol runtime paths. Traditional Python UT uses nexent-python-tests separately; every product change assesses it, not only changes that break existing tests.

Before adding a new D1 implementation, apply case-design.md's admission check against actual UT/formal assertions. Reuse or strengthen tests at the appropriate boundary; do not create a formal copy or wrapper of UT. The script must execute the declared internal collaboration, not replace it all with mocks and call-count checks. During assertion review, confirm its claimed additional evidence actually exists. If a designed new Case is redundant or misclassified, resolve the authoritative design before implementation; do not silently reclassify existing D1 or discard necessary higher-boundary proof.

Each collected item must expose its Case ID in stable metadata or its test title. Do not create constant assertions, swallow failures, use skip or xfail as completion, or change expectations to mirror the current implementation. Scripts may not depend on developer absolute paths or specific SQL filenames.

After implementation, collect the exact selector and run it. Bind it in the owning Case's `execution.yaml` (primary file is relative to that Case directory); the validator derives hashes and registry entries. Run the full formal-asset validator, then check the affected Case IDs in the generated registry and Excel view.

## Preparation and delivery gate

For each added or changed active automated D2-D5 Case, assess its logical assets,
controlled services, owned processes, cleanup and recovery before writing
`execution.yaml`. Declare `preparation` explicitly. For a self-contained Case,
use `families: []` and explain in binding notes or the change record how it creates
and releases its own resources; leave anchors, special assets and D4 groups off
unless actually needed. Do not add factories merely to satisfy validation, or
empty a real dependency list to make a gate pass.

The default implementation validator checks preparation for all active D2-D5
bindings without an opt-in flag. Design may precede executable preparation.
Strict design/implementation checks also require unique responsibility routing.
Run the affected preparation-test-cleanup flow through the suite worker, checking
cleanup receipts and owned process/resource release even on failure. Missing
preparation blocks that Case in Daily; it is never inferred or counted as PASS.

Before delivery/merge, reconcile the current target branch using the team's merge
or rebase policy, then rerun strict asset validation and applicable regressions
on the combined tree. Record the target revision, validated working-tree revision
and uncommitted state with evidence. Instructions alone cannot ensure that remote
PR checks ran; do not claim required-check enforcement or change CI without authority.

For new/acceptance-modified Cases follow [acceptance-integrity.md](acceptance-integrity.md). Validate every obligation and actual reported test name, check the assertions against the contract and retain evidence. A script PASS, valid binding or unchanged hash is not semantic certification. Do not auto-mark a missing obligation complete or shrink expectations to fit an incomplete script.
