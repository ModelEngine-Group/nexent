# NL2Agent behavior versus implementation

## Scope and evidence

This audit uses the complete canonical design at `doc/docs/zh/developer-guide/nl2agent-design.md`. It identifies baseline `4e7d9fe15c78d85c732beb9fe06ac8d439e99327` and snapshot `5375990a0336644b84ddb4307c8d3d4199f1976b`. The requested `docs/nl2agent-refactor/current-implementation-design.md` does not exist in this checkout. Code, tests, generated contracts, Git history and the exact 177-file diff are secondary evidence.

No user-visible capability is optional. “Replace” means replace the mechanism while preserving observable behavior, ownership, idempotency, recovery and contract semantics.

## Subsystem decisions

| Subsystem | Required behavior | Current mechanism | Existing Nexent capability to reuse | Duplication / unnecessary layer | Clean reconstruction | Risk |
|---|---|---|---|---|---|---|
| Runner and Draft | Tenant Runner executes; separate version-0 Draft receives configuration | Seed service, default JSON, facade assembly, name filtering | Agent create/update, tool binding, versioning, list filtering | Readiness checks and dependency wrappers repeat | One idempotent provisioner; persist Runner ID; write only through existing Draft services | Medium |
| Session lifecycle | Atomic start, owner discovery, Conversation recovery, abandon, completion and retention | Session/lifecycle services, DB repository, store/cache | Caller-owned SQL transactions and existing Conversation/Agent soft deletion | PostgreSQL and Redis expose parallel reads | One Session repository; PostgreSQL-only state/catalog reads | Medium |
| Workflow | Deterministic stage/action gates, strict revision, batches and Delivery | Pure evaluator; strict JSONB model; session_catalog; store; workflow service | PostgreSQL conditional update and domain error mapping | One aggregate is scattered across evaluator, Redis-era repository, store, service and facade | Keep pure evaluator and one Workflow aggregate/repository with revision CAS | High |
| Requirements | Five fields, normalized summary, fingerprint, Card registration/confirmation and correction reset | Prompt + workflow/repository functions | Chat messages/history | Phase checks repeat in prompt, service, Card and lifecycle | Three domain commands: register, confirm, revise; one generated projection | Medium |
| Models | Primary plus ordered fallback; tenant/type/availability/output validation; Finalize recheck | Agent update plus workflow projection and compensation | Existing model APIs and Agent transaction | Selected status duplicated in state | Agent fields remain truth; update Agent and Session in one transaction | High |
| Local resources | Search, declared config, atomic Apply/Skip, secret redaction | Snapshot + SDK search + proof + resource service reservations | list_all_tools, Skill DB, ToolInstance/SkillInstance | Proof and recommendation batch duplicate IDs; reservations compensate split commits | Inline catalog; one recommendation object; binding and state in one transaction | High |
| Online catalogs | Registry/Community fail-soft, official required, stable normalized search | Catalog service snapshot; SDK MCP normalizer | Existing marketplace and official Skill services | Backend redaction and a large SDK normalizer split one adapter concern | Normalize and redact once in Backend; SDK only scores normalized records | Medium |
| Shared scoring | Multilingual normalization, fuzzy matching, stable top five | Pure helpers mixed into SDK context | RapidFuzz and jieba | Context/proof/scoring share a module | Pure scoring module plus three thin Tool adapters | Low |
| Trusted proof | Exact ordered search output precedes actionable Card | Trusted map plus separately registered recommendation map | Session revision CAS | Two state maps encode one batch | One recommendation object transitions searched → presented → resolved | High |
| Cards | Seven logical Cards/nine tags; strict schema; latest completed message Delivery | Canonical schema, Backend validator, Frontend Ajv, hand DTOs | OpenAPI/TS generation and Conversation DB | Payload DTOs and parsing checks repeat | One reusable verifier, generated TS, one frontend AST/registry | High |
| Continuation/recovery | Hidden continuation, two Card retries, complete refresh/switch recovery | Provider, lifecycle/recovery hooks, three chat helpers | Existing agent run/history | Multiple ID maps, flags and projections | One Session-scoped Provider and continuation coordinator | High |
| MCP install/bind | Explicit configuration, idempotent serialized saga, health/discovery, bind/skip, recovery | Large MCP service, Redis lock/heartbeat, JSON reservations | remote_mcp_service, discovery/upsert, ToolInstance writes | Lock and operation state live in different stores | Durable operation row + lease + advisory-lock claim; existing service adapters | High |
| Skill install | Install/recover official Skill and bind immediately | Catalog service + Redis lock + synchronous installer + SkillInstance | Existing official ZIP installer and SkillService | Installation is misplaced in catalog service and blocks async worker | Installation adapter/checkpoints; run blocking work off event loop | High |
| Identity/Finalize | Display name, persisted-truth review, strict Finalize to draft_ready | Publication and summary services | Existing Agent/resource/model services | Summary DTOs repeat persisted projections; “publish” name is misleading | DraftFinalizeService; one transaction updates Draft and Session | High |
| Generated/deploy | Reproducible contracts and one convergent schema | Export/sync scripts; five unreleased migrations; repair tool | FastAPI generator and standard migration runner | Prototype migrations/backfills/repair are unnecessary before release | Regenerate at PR boundaries; one final migration + fresh schemas | Medium |

## Replaceable projections

Redis copies of state/catalog, the shared content-addressed catalog table, dependency-bundle dataclasses, facade aliases, handwritten frontend response DTOs, unreleased state compatibility, five prototype migrations and wrapper-mock tests are not product behavior.

Workflow revision, exact recommendation order, registration, installation checkpoints/results, Delivery/retry count, requirement fingerprint, configured-without-value flags and lifecycle status are behavior. They remain durable in the simplified model.

## Classification rule

- `BASELINE_CORRECTNESS`: ownership/identity, tenant scope, secret non-propagation, strict references/requests, Finalize revalidation, explicit side effects, idempotency, concurrency and transaction/compensation.
- `ADVANCED_SECURITY`: destination address policy, DNS pinning/rebinding defense, pinned transports, proxy/trust-env restrictions, cross-host redirect restrictions and abuse ceilings.
- `MIXED`: URL validation, capacity bounds, leases and redirects where correctness and attack mitigation overlap. The correctness portion remains.
