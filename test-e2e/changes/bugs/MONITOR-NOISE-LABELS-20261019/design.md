# Design — monitoring export noise and built-in display names

## Context and scope

Change: MONITOR-NOISE-LABELS-20261019. Baseline inspected on 2026-10-19 at
`d43dfc0db89ada18a768d5ea8c483eae66d0ac72` on `develop`.
The user requests suppression of three Elasticsearch operation reports and Chinese
Workbench/skill-creator monitoring names. The owning boundaries are SDK monitoring
(F-169) and the ephemeral NL2Skill configuration (F-078).

The expected sibling `nexent-doc` and `nexent_SPEC` directories are unavailable.
Searches of repository documentation and available Documents/Downloads/Desktop
found no usable monitoring SPEC. This local design preserves current acceptance;
document-repository synchronization remains deferred until that baseline is available.

`MonitoringSpanProcessor.on_end` already suppresses Elasticsearch
`indices.get_alias` before the batch export queue. The existing
`test_elasticsearch_spans.py` uses the real Elasticsearch client, tracing provider,
processor and in-memory exporter with a controlled transport. Its retained-operation
test currently expects `search` to be exported. `start_agent_run` already uses
`agent_display_name` to name a trace, preserving the executable `agent_name`.
`RuntimeMountService.resolve_root` propagates a Workbench runtime identity's display
name into its request-scoped configuration; NL2Skill currently has no display name.

## Final behavior and design

Keep normal tracing, batch lifecycle, error behavior and disabled monitoring paths.
Filter only spans with `db.system=elasticsearch` whose `db.operation` is `search`,
`indices.stats`, `indices.get_settings`, `indices.get_alias`, `bulk`,
`indices.exists` or `indices.delete`. Also suppress the exact span names
`knowledge.process.submit` and `knowledge.upload.batch` at the same export boundary.
Match Elasticsearch attributes rather than its span names so ordinary tools remain
visible. Knowledge name matching is exact; other ingestion steps remain visible.
No Elasticsearch operation is skipped, and its response/error still reaches its caller.

The lists above are defaults. Backend environment variables
`MONITORING_EXCLUDED_ELASTICSEARCH_OPERATIONS` and `MONITORING_EXCLUDED_SPAN_NAMES`
replace the respective list when set. An unset variable retains its default;
an explicitly empty value disables that filter. Comma-separated entries are trimmed,
empty entries ignored and duplicates removed. Matching is case-sensitive and exact,
with no regex or wildcard expansion. The two lists are independent. Backend reads
remain centralized in `consts.const`; bootstrap passes explicit SDK configuration
to each processor. SDK callers can provide the same values without environment
access. Configuration is loaded at startup; changes require a backend restart.
Docker/K8s already forward `monitoring.env` to backend services, so no deployment
script, chart or running-system change is needed.

Assign `智能工作台` to the system Workbench root's runtime identity and
`技能创建助手` to NL2Skill's `AgentConfig.display_name`. Preserve `workbench_main`,
`__skill_creator__`, child identities and stored published snapshots. In particular,
do not alter the provider's release manifest or persisted display name: existing
tenants must not encounter same-revision provisioning drift. Bootstrap presentation
is outside this monitoring-name fix. Existing trace naming consumes these runtime labels.

## Current acceptance

- AC-001: All four filtered operations are absent from exported spans on success
  and failure. Their real client transport still executes and returns/raises normally.
- AC-002: Other Elasticsearch operations, operations from another database,
  unattributed spans, Agent/LLM spans and business search tools remain exported;
  retained spans preserve parents. Processor flush/shutdown behavior is retained.
- AC-003: Legacy, absent and Chinese Workbench snapshot labels produce the Chinese
  system runtime display name without modifying snapshots or child names. NL2Skill
  has its Chinese display name while keeping its executable name and options.
- AC-004: Existing SDK trace naming exports Chinese display names without replacing
  execution identifiers; nested spans cannot rename the main trace.
- AC-005 (October 21 follow-up): Suppress `bulk`, `indices.exists` and
  `indices.delete` telemetry on success/error without changing real client calls.
  Suppress `knowledge.process.submit` and `knowledge.upload.batch` for root/nested
  sync/async execution without changing business results, exceptions or metrics.
- AC-006 (October 21 follow-up): Keep other Elasticsearch operations, same-named
  non-Elasticsearch spans, other knowledge stages and knowledge name suffixes.
  Retain Agent/LLM/tool spans and parent relationships for the remaining spans.
- AC-007 (configuration follow-up): Unset environment variables preserve the seven
  Elasticsearch and two knowledge defaults. Explicit values replace each list,
  including custom names; explicit empty values disable the respective filter.
  Whitespace, duplicate and empty comma entries normalize predictably. Lists remain
  independent and isolated across SDK configs/processors. Invalid SDK list types
  raise a configuration error rather than silently disabling filtering.
- AC-008 (configuration follow-up): Backend constants and both bootstrap import
  paths forward default, custom and empty values through real SDK configuration.
  The real manager/provider/batch-export path applies those values while preserving
  exact matching, Elasticsearch database scoping, retained parents and exporter
  lifecycle. Missing optional OpenTelemetry dependencies still degrade safely.

## Traditional UT + D1-D5 responsibilities

| Feature / AC | Traditional UT | D1 | D2 | D3 | D4 | D5 | Rationale |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-169 / AC-001,002 | Strengthen Elasticsearch exporter tests, including controlled transport failures and retained tool/parent assertions | UT-SDK-014 regression only | N/A | N/A | N/A | N/A | Export/configuration rules; no HTTP, provider, browser or deployment contract changes |
| F-078 / AC-003 | Strengthen NL2Skill configuration assertion; add Workbench runtime label variants | No new Case | N/A | N/A | N/A | N/A | Bounded configuration rules, no model invocation required |
| F-169 / AC-004 | Reuse trace-name and direct SDK display-name tests | UT-SDK-014 regression only | N/A | N/A | N/A | N/A | Existing trace propagation assertions; no duplicate formal component Case |
| F-169 / AC-005,006 | Strengthen existing client/export tests and exercise actual knowledge decorators with controlled resource/metric boundaries | UT-SDK-014 regression only; no duplicate Case | N/A | N/A | N/A | N/A | Filter rules change; storage, transport and ingestion business behavior remain unchanged |
| F-169 / AC-007,008 | Add SDK configuration/real batch-export assertions and isolated backend environment/bootstrap tests; reuse default filter regressions | UT-SDK-014 unchanged parser regression; no duplicate Case | N/A | N/A | N/A | N/A | Bounded configuration/export rule; existing environment-file forwarding remains unchanged; no live ingestion, model, browser or deployment contract change |

The formal `UT-SDK-014/test.py` checks parser robustness and signal-specific OTLP
endpoints. Its execution does not establish current filtering or localization
acceptance, nor does it certify all of its historical written acceptance obligations.
No formal Case is added or relabeled. Existing UT supplies the required unit proof.

## Acceptance traceability

| AC | Code areas | Traditional UT | Formal Cases | Evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-001,002 | SDK monitoring span processor | `test/sdk/core/agents/observability/test_elasticsearch_spans.py` | UT-SDK-014 regression only | Real client/provider/processor/exporter with controlled transport: included in 131 passing UT | PASS |
| AC-003 | Workbench runtime resolution, NL2Skill configuration | `test/backend/services/test_workbench_monitoring_labels.py`, `test_nl2skill_service.py`; existing Workbench suites for child/default/error regressions | No new Case; unit boundary | Chinese names and preserved identities: included in 131 passing UT | PASS |
| AC-004 | Existing Agent run trace naming | `test/sdk/core/agents/observability/test_trace_name.py`, `test_agent_display_name.py` | No new Case; unit boundary | Real in-memory trace assertions: included in 131 passing UT | PASS |
| AC-005,006 | SDK span export filtering | `test/sdk/core/agents/observability/test_elasticsearch_spans.py`, `test/backend/utils/test_monitoring_knowledge_filter.py`; existing knowledge telemetry and trace-name regressions | UT-SDK-014 regression only | Follow-up reproduction: 24 failed, 28 passed; after fix: 91 passed | PASS |
| AC-007,008 | Backend constants/bootstrap; SDK configuration and span processor | `test/sdk/core/agents/observability/test_monitoring_exclusions.py`, `test/backend/utils/test_monitoring_exclusions.py`; existing monitoring and default filter regressions | UT-SDK-014 regression only | 44 focused configuration UT included in 135 current exporter/configuration regressions; separately 21 backend and 96 legacy SDK monitoring UT | PASS |

## Verification evidence

- Before the production fix, the targeted reproduction reported **10 failed,
  15 passed**. Six failures showed the three unwanted spans still exported on
  success/error; three showed missing/legacy Workbench labels; one showed the
  absent NL2Skill display name. The existing Chinese-label variant already passed.
- Traditional UT command, run from the repository with Python 3.11.9:

  ```sh
  .venv/bin/python -m pytest test/sdk/core/agents/observability/test_elasticsearch_spans.py test/sdk/core/agents/observability/test_trace_name.py test/sdk/core/agents/observability/test_agent_display_name.py test/backend/services/test_workbench_monitoring_labels.py test/backend/services/test_workbench_service.py test/backend/services/test_workbench_service_coverage.py test/backend/services/test_nl2skill_service.py -q
  ```

  Result: **131 passed in 4.43s**. This is separate from formal Case execution;
  no coverage percentage is claimed.
- Formal regression command:

  ```sh
  .venv/bin/python test-e2e/infra/tools/run_cases.py UT-SDK-014 --test-home "$NEXENT_TEST_HOME"
  ```

  Result: **UT-SDK-014 PASS**. Evidence relative to the machine-local test home:
  `runs/repository-local/20261019T090859797468Z-UT-SDK-014`.
  This is configuration-parser regression execution only, not certification of
  every historical written obligation or deployed Langfuse acceptance.
- The design-phase unified validator passed with `--generate
  --require-ut-change MONITOR-NOISE-LABELS-20261019`. The copyright checker passed
  for all six changed/new Python files. Implementation-phase validation with
  `--generate --require-ut-change MONITOR-NOISE-LABELS-20261019` and the subsequent
  read-only generated-view check both passed. `git diff --check` also passed.

No deployed Langfuse session is claimed. Changes apply to newly emitted telemetry;
existing stored traces are not modified.

## Merge verification — 2026-10-20

Merged `origin/develop` at `a2f53b39d` into `dev/monitor-name`. Both textual
conflicts were copyright-header whitespace. Keep the upstream move from
`backend/services/workbench_service.py` to
`backend/management/services/agent/workbench.py`, retain the Chinese runtime
label and NL2Skill display-name assertions, and update the branch-local Workbench
label test to import `management.services.agent.workbench`.

The same seven-file UT command above passed again: **131 passed in 5.03s**.
Copyright checks for the three resolved/adapted Python files and
`git diff --check` passed. Generated formal views needed refreshing after the
upstream asset merge; implementation validation with generation and its subsequent
read-only check both passed.
The separate `UT-SDK-014` runner could not start because the existing machine-local
test home's `config/daily.env` is missing. Its prior PASS remains historical
evidence; no new formal Case execution PASS is claimed for this merge.

## Merge verification — 2026-10-21

Merged `origin/develop` at `d7f5955da` into `dev/monitor-name`. The sole textual
conflict was copyright-header whitespace in `backend/agents/nl2skill_agent.py`.
Retain `display_name="技能创建助手"` together with upstream's empty-prompt
validation, explicit prompt templates and request-scoped system context items.
The auto-merged NL2Skill configuration test retains both the Chinese display-name
assertion and upstream's context-item assertions.

- The seven-file monitoring/Workbench/NL2Skill UT command recorded above passed:
  **131 passed in 3.43s**.
- Additional upstream regression selection:
  `.venv/bin/python -m pytest test/backend/services/test_nl2skill_prompt.py test/backend/services/test_nl2skill_continuation.py test/backend/services/test_nl2skill_stream.py -q`:
  **49 passed in 3.56s**. These check localized prompt/context construction,
  empty inputs, request isolation, continuation history and stream/retry behavior.
- Implementation-phase formal-asset generation and subsequent read-only validation
  with `--require-ut-change MONITOR-NOISE-LABELS-20261019` both passed.
- Copyright validation for the resolved Python file and branch-difference
  whitespace validation against `origin/develop` passed.
- The former machine-local formal test-home configuration remains unavailable;
  no formal Case runtime execution or deployed-model acceptance is claimed.

## Additional suppression — 2026-10-21

The user reported and authorized suppression of five additional names in the
monitoring screenshot. At this checkpoint the branch is based on `0e6db8df3`.
`bulk`, `indices.exists` and `indices.delete` are native Elasticsearch spans;
`knowledge.process.submit` originates from the ingestion service decorator and
`knowledge.upload.batch` from the file service decorator. Both decorators use
`infrastructure.observability.knowledge.knowledge_span`. All flow through the
existing `MonitoringSpanProcessor` export boundary, so no caller, storage or
knowledge execution change is needed. Filtering remains exact, preserving other
knowledge steps and non-Elasticsearch operations with matching names.

The pre-fix targeted reproduction reported **24 failed, 28 passed**. All failures
were unwanted exported spans: eight Elasticsearch variants (including existing
alias tests now checking `indices.exists`) and sixteen sync/async, root/nested,
success/error knowledge-decorator variants.

After the filter change, the following traditional UT selection reported
**91 passed in 1.44s**:

```sh
.venv/bin/python -m pytest test/sdk/core/agents/observability/test_elasticsearch_spans.py test/backend/utils/test_monitoring_knowledge_filter.py test/backend/utils/test_knowledge_telemetry.py test/sdk/core/agents/observability/test_trace_name.py test/sdk/core/agents/observability/test_agent_display_name.py -q
```

The tests exercise the actual Elasticsearch client with a controlled transport,
the real knowledge decorators with controlled resource and metric boundaries, and
real providers/processors/in-memory exporters. They assert return/error behavior,
metric callback retention, exact matching, retained Agent/model/tool/knowledge spans
and retained parent relationships. The existing formal parser Case is unchanged:
it adds no new proof of this bounded export rule, so no duplicate D1 is introduced.
Copyright checks for all three changed/new Python files and `git diff --check`
passed. Design-phase validation with the selected Change also passed.
Implementation-phase generation and the subsequent read-only generated-view check
both passed with `--require-ut-change MONITOR-NOISE-LABELS-20261019`.
The `UT-SDK-014` runner was retried and remained **BLOCKED** before collection:
the machine-local test home's `config/daily.env` is missing. This is distinct from
the 91 passing traditional UT; no new formal runtime PASS is claimed.

## Configurable exclusions — 2026-10-21

Implemented two independent startup variables in `backend/consts/const.py` and
passed them through both bootstrap imports into `MonitoringConfig` and the batch
span processor. SDK-only defaults and normalization live in a dependency-free
module, retaining graceful degradation without OpenTelemetry. Each processor
snapshots its configured sets; environment access is not added to the SDK.
The tracked `deploy/env/monitoring.env.example` documents replacement, explicit
empty values, exact matching and restart/recreation. Local environment files and
running services were not changed. Existing Compose environment files and K8s
monitoring-env secrets already forward these settings.

Traditional UT results (Python 3.11.9):

```sh
.venv/bin/python -m pytest test/sdk/core/agents/observability/test_monitoring_exclusions.py test/sdk/core/agents/observability/test_elasticsearch_spans.py test/backend/utils/test_monitoring_exclusions.py test/backend/utils/test_monitoring_knowledge_filter.py test/backend/utils/test_knowledge_telemetry.py test/sdk/core/agents/observability/test_trace_name.py test/sdk/core/agents/observability/test_agent_display_name.py -q
# 135 passed in 2.19s

.venv/bin/python -m pytest test/backend/utils/test_monitoring.py -q
# 21 passed in 0.48s

.venv/bin/python -m pytest test/sdk/monitor/test_monitoring.py -q
# 96 passed in 0.54s
```

The two new configuration files contain 44 collected variants. Assertions cover
default parity with the tracked example, backend environment reads and both
bootstrap import paths, replacement/empty/independent lists, whitespace/duplicates,
invalid SDK input errors, per-instance isolation, absence of SDK environment reads
for these settings, optional-dependency degradation, case-sensitive literal matching
(including wildcard-like input), database scoping and real batch-export wiring on
success/error. Export tests retain parent relationships and default-filter business
regressions. Backend and legacy SDK monitoring suites run in separate pytest
processes because the legacy SDK conftest intentionally replaces OpenTelemetry with
mocks; their results are separate from the real in-memory exporter assertions.

Copyright validation passed for all ten changed/new Python files, and
`git diff --check` passed. An optional Ruff check could not execute because
`.venv/bin/ruff` is not installed; no lint PASS is claimed. Design-phase formal-asset validation with
`--require-ut-change MONITOR-NOISE-LABELS-20261019` passed before implementation.
Implementation-phase generation and the subsequent read-only validation with the
same selected Change both passed after implementation.
No formal Case was added or modified: the existing parser Case adds no new
exclusion-list proof beyond these UT. `UT-SDK-014` remains **BLOCKED** by the
previously recorded missing machine-local `config/daily.env`; no repeated run or
formal runtime PASS is claimed while that prerequisite is unchanged.
