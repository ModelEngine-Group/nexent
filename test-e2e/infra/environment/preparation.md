# Case preparation execution

`run-suite.py run/daily --execute` selects formal Cases, reads their execution
metadata, and starts `suite.worker` with a Case-local result directory. This is
fixed Python orchestration, not an LLM deciding which setup to perform.

| Field | Behavior |
| --- | --- |
| `anchors: true` | Start controlled HTTP/MCP services and run `prepare_anchor_assets.py` against machine configuration |
| `families: [completed_evaluation]` | Run `python -m shared.prepare_local_assets --family completed_evaluation`; dispatch to `shared.factories.evaluation.prepare_completed_run()` |
| `special_assets: true` | Run `prepare_special_assets.py --case <Case-ID>` |
| `d4_groups: [...]` | Run `prepare_d4_shared_assets.py` with only the declared groups and a Case-local output environment file |

Order: controlled services -> anchors -> families -> special preparation -> D4
groups -> fixed test -> registered-resource cleanup -> service shutdown. Empty
lists/false mean that step is not requested. Preparation failure prevents that
Case's test from running; created resources remain journaled for cleanup. Batch
retention policy may intentionally retain failed-run resources; check the cleanup
receipt rather than assuming deletion. No script-hash approval is required.

Factories use machine configuration and store IDs in the Case run's
`runtime/resolved-assets.yaml` and `runtime/asset-journal.jsonl`. Tests resolve
logical assets through existing helpers; they do not use another test Case as a
producer. Resources whose creation is itself under test are created inside the
test and journaled there, not pre-created to bypass the tested operation.

`infra/tools/run_cases.py` remains a low-level direct runner; it does NOT perform
this preparation orchestration. Use `infra/scripts/run-suite.py run --case
<Case-ID> --test-home <external-directory> --execute` when automatic preparation
and final cleanup are needed. Without `--execute` this entrypoint only plans.

Static audio/images/documents are separate inputs. See
[static-assets-migration.md](static-assets-migration.md) for placement and pending
provisioning/preflight work.
