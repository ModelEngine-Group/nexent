# NL2Agent reconstruction summary

## Current size

The design fixes the comparison at baseline `4e7d9fe15c78d85c732beb9fe06ac8d439e99327` and snapshot `5375990a0336644b84ddb4307c8d3d4199f1976b`: 178 commits, 177 changed files, 42,236 additions and 1,400 deletions. It reports 114 production/deploy files with 26,923 changed lines and 52 test/config files with 14,391 changed lines. The hand-written core is concentrated in approximately 12,000 lines across NL2Agent Backend/SDK/Frontend modules, including 1,019-line facade, 1,208-line workflow/catalog module and 920-line MCP service.

## Behavior that remains

All documented behavior remains: five-field conversation; registered and explicitly confirmed requirements Card; primary/ordered fallback models; local Tool/Skill search, configuration, Apply/Skip; Registry, Community and official Skill searches; exact trusted recommendations; MCP configuration/install/health/discovery/bind/skip; official Skill install and resource_missing recovery; identity; persisted-truth final review and version-0 draft_ready Finalize; durable owner-scoped Session/Conversation recovery; strict Cards, registration and Delivery; hidden continuation; two automatic Card retries; refresh and Conversation switching.

Baseline identity, tenant, secret, request/reference, Finalize, explicit-action, idempotency, concurrency and transaction/compensation guarantees remain mandatory.

## Implementation removed or consolidated

- PostgreSQL becomes the sole workflow/catalog authority; all NL2Agent Redis projections are removed.
- Redis installation locking becomes a durable operation lease plus short PostgreSQL advisory-lock transactions.
- The content-addressed catalog table becomes an inline immutable Session catalog.
- Trusted proof and recommendation lifecycle become one object.
- Model/resource truth is no longer duplicated into workflow state.
- Facade pass-throughs, function bundles and redundant summary/DTO wrappers are consolidated.
- MCP provider normalization moves to Backend catalog adapters; SDK Tools become thin stateless searches.
- Frontend handwritten API/Card DTOs and scattered lifecycle flags become generated types plus one Provider/coordinator.
- Five unreleased migrations and the repair script become one final migration and matching fresh schema.
- Mock-call-only and Redis-implementation tests are replaced by persistence/service/browser boundary tests.

## Scope by PR

| PR | Rough review scope | Principal risk |
|---|---:|---|
| PR1 Core Workflow | Session/domain/repository, Runner/Draft, requirements/models/identity/Finalize, core UI/contracts | Identity and workflow gate correctness |
| PR2 Local Resources | local adapter/search/proof/config/binding/Card | Atomic binding and secret handling |
| PR3 Online Catalogs | three provider adapters, normalization/search/proof/Cards | Catalog normalization parity |
| PR4 Installation | operation schema/lease, MCP/Skill saga, discovery/binding | External side effects, concurrency and recovery |
| PR5 Release | Delivery/retry/continuation/recovery, final migration/contracts/E2E/enablement | Cross-layer races and deployment parity |

Every intermediate PR keeps the feature disabled. The stack is not releasable until PR5.

## Database and Redis

Final schema has `nl2agent_session_t` with identity, lifecycle, revision, strict workflow JSONB and inline catalog JSONB, plus `nl2agent_installation_operation_t` with unique secret-free idempotency key, checkpoint, lease, result and redacted failure. Existing Agent/Conversation/model/MCP/Tool/Skill tables remain authoritative.

Redis usage falls from state, catalog, shared snapshot and lock to zero. This is a dependency reduction, not loss of concurrency or recovery.

## Deferred security

Deferred controls are advanced MCP destination defenses: private/loopback/link-local blocking, DNS snapshot pinning, rebinding protection, pinned transports, proxy/trust_env restrictions, cross-host redirect restrictions and Unix socket transport defenses. Security-oriented byte/capacity tuning may also follow later.

Minimum first-release fallback keeps HTTP/HTTPS-only URLs, rejects embedded credentials, uses TLS verification, accepts only trusted declared options, excludes proxy/socket fields from the Card/LLM, preserves owner/tenant checks and secret redaction, and retains finite provider loading.

## Disputed classifications

- Installation locks are `MIXED`: Redis is replaceable, but serialization/owner-safe leases are baseline and cannot be deferred.
- URL controls are `MIXED`: advanced destination pinning may defer; scheme/userinfo/TLS and strict trusted options stay.
- Capacity is `MIXED`: abuse-tuned values may simplify; finite paging, request shape bounds, model count and collection validity stay.
- Cross-host redirect defense is advanced, but disabling all redirects may affect normal MCPs; the adapter choice remains an open deployment question.

## Major merge blockers

1. Missing requested primary document path/provenance confirmation.
2. Agreement on the final migration identifier and fresh-schema paths.
3. A proven Skill filesystem/DB recovery strategy.
4. A real PostgreSQL concurrency suite for leases, CAS and transactional binding.
5. End-to-end Card Delivery/continuation tests across refresh and Conversation switching.
6. Generated-contract reproducibility and one clean deployment migration.

## Recommended first clean-branch task

Create the feature flag and the strict, PostgreSQL-only `Nl2AgentWorkflow` domain plus Session repository contract, with table-shape migration draft and real transaction tests, but no enabled route. This is the smallest foundation that fixes the authority boundary before porting any feature logic.

## Audit verification

- Read all 611 lines of the canonical design; the requested alternate path is absent and recorded in open questions.
- Feature ledger: 53 capability rows; every row has a target PR or generated-contract target; none is omitted/deferred.
- Changed-file ledger: exactly 177 unique rows, identical to the baseline-to-snapshot path set.
- Test ledger: exactly 52 unique changed test/config rows, identical to the design's test classification set.
- Security deferrals are advanced destination/abuse hardening only. Every MIXED control states the baseline portion retained.
- MCP and Skill flows retain explicit action, stable secret-free idempotency key, concurrency ownership, durable checkpoint/retry and compensation.
- Tenant/user/Runner/Draft/Conversation identity, tenant resource scope, strict references, Finalize revalidation and all Secret invariants remain.
- Workspace verification found only the 16 requested files under `docs/nl2agent-refactor/`; no production source or existing test was modified.
