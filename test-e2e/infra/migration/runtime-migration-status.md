# Repository runtime migration status

This is a candidate runtime, not an approved Ubuntu Daily replacement.

## Implemented in this increment

- Standard-library bootstrap planner with explicit execution, backend frozen lock and Node lock consumers, per-machine Python/browser paths. Existing product dependency versions are not changed.
- Plan selection by Case, stage, Feature or Change, using the existing case-local contracts and delta schema.
- Dependency/config preflight, including detection of missing product packages such as reportlab and croniter.
- Shared local batch lock, pinned HEAD/test content, per-case process timeouts, checkpoint journal, terminal receipts, D0-D6 stage state and JSON/Markdown reports.
- Existing case runner reused without replacing its JUnit/TAP/Playwright outcome rules. Existing uncommitted changes are retained.
- Explicit preparation metadata in case-local execution.yaml, with schema validation but no script-hash approval. Missing online declarations remain configuration blockers.
- Anchor, D4 and special asset preparers migrated from the source suite. D4 groups must be explicitly supplied, and generated environment output is case-local.
- Controlled HTTP/MCP server code and per-case lifecycle migrated. Existing container-host configuration is required explicitly; wire logs stay under the Case run directory. Live protocol/container reachability has not yet been verified.
- Existing registered-asset cleanup reused. Cleanup failure remains separate from the test result. Unsafe D5 timeout/recovery blocks continuation.
- Final-report notification adapter based on the original lark-cli command, opt-in only, no incomplete-batch reports and no automatic retry of uncertain sends.
- Candidate local `run` resume: finalized clean interruption only, same tracked/untracked product and test source plus local config fingerprint, static-asset recheck, contiguous journal/receipt/cleanup validation, new child batch retaining prior evidence. Unknown in-flight work is blocked pending manual recovery. It does not resume Daily deployment hooks.

## Not yet complete / not certified

1. Preparation declarations are migrated for all 449 active non-D1 Cases: D2 150, D3 173, D4 45, D5 81. D4 uses explicit per-Journey groups; CMSR-D2-001 is process-local. The 20 changed D5 Cases retain the existing prerequisite families. The final three D3 Cases now declare anchors with no external family: tag capacity creates its own definitions and controlled tool, asset-owner lifecycle journals its own KB/token, and parent-task persistence uses the real temporary-KB context instead of an unregistered DB-only row. Each owned tag definition is journaled before assertions; cleanup discovers its exact child values through the product API and can be scoped by Case ID. These setup/cleanup corrections are declared migration differences, not live parity certification. Asset-owner testing still requires its feature and configured account; tag capacity still requires the isolated test environment.
2. Controlled HTTP/MCP protocol and container-reachability parity still need a live isolated-stack verification.
3. The old extra Python requirements were ranges/unpinned input, not a real lock. The SDK-only dependency closure and Linux browser OS libraries need resolution/verification. No dependencies were installed in this increment.
4. Isolated Compose/data/port settings and build/deploy/health commands need adaptation to the actual deployment. The candidate refuses empty Daily hooks. It neither fetches Git nor changes image tagging or container recreation policy.
5. Local clean-interruption resume has offline regression coverage, but an actual interrupted D1-D5 run and forced-timeout cleanup/recovery parity still need live verification. Daily resume and deployment identity validation remain unavailable. Do not manually reuse old receipts as passes.
6. The 23-file static catalog, checksum preserving plan/apply/verify command and D0 checks are implemented. All 23 payloads were copied byte-for-byte into uncommitted `infra/assets/` and verified against the catalog; the isolated output test home also verified all 23 bytes. Reference reconciliation, content/licence/privacy review before commit, and stronger PCM/oracle semantics remain; see `infra/environment/static-assets-migration.md`. Report-format/owner mapping parity and live notification verification also remain. No real notification was sent.
7. Full D1-D5 execution and original-suite same-commit comparison have not run through this candidate. No GitHub workflow, Ubuntu deployment or scheduled task was changed.

The offline regressions cover missing/duplicate results, blocked classification, process timeout, lock exclusion, incomplete notification suppression, uncertain delivery deduplication, Change selection, missing preparation declarations, execution without prerequisite hash approval, and continuing independent Cases after failure. They also verify service/anchor/family/special/D4/test/cleanup ordering, case-local prepared environment output, cleanup after preparation timeout, controlled-service readiness and shutdown. These validate the controller, not product behavior.
