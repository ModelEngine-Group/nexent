# NL2Agent target architecture

## Outcome

Use one PostgreSQL-owned Session aggregate, existing Nexent Agent/Conversation/model/resource services, a small pure workflow domain, normalized immutable per-session catalogs, persistent installation operations and one Conversation-scoped frontend Provider. NL2Agent no longer requires Redis. The feature flag remains disabled through PRs 1–4 and is enabled only after PR 5 completes the stack.

## Boundaries

Backend:

- `nl2agent_app` authenticates, parses strict requests and maps domain errors.
- `Nl2AgentSessionService` starts, discovers, recovers and abandons Sessions.
- `Nl2AgentWorkflow` contains the strict state and pure evaluator.
- `Nl2AgentRepository` performs owner-scoped reads and revision-CAS writes; the catalog is inline and immutable.
- `Nl2AgentResourceService` owns recommendation presentation and local Apply/Skip, delegating binding.
- Catalog adapters load, bound, normalize and redact local, Registry, Community and official sources.
- `Nl2AgentInstallationService` owns durable MCP/Skill sagas and delegates actual side effects.
- `Nl2AgentFinalizeService` owns identity, review projection and atomic Finalize.
- One Card verifier handles canonical parsing, contextual proof and Delivery checks.

There is no umbrella facade re-exporting all subordinate functions and no bundles of function-valued dependency dataclasses.

SDK:

- Keep three per-run Runner-visible search Tools.
- Make shared tokenization/scoring pure and stateless.
- Accept already normalized/redacted catalogs and one proof callback.
- Never access environment variables, Redis, PostgreSQL or mutable process-global state.

Frontend:

- One Provider is keyed by durable Session ID and validates recovered Conversation, Runner and Draft.
- Generated API/Card types replace handwritten DTOs.
- One registry maps nine fence tags to seven logical components.
- One coordinator orders parse → register → mount → Delivery and action → refresh → optional hidden continuation.
- Session storage is a one-time navigation hint only.

## Runtime

~~~mermaid
flowchart TD
  E[Builder entry] --> S[POST session/start]
  S --> T[DB transaction: Draft + Conversation + Session/catalog]
  T --> R[Existing /agent/run]
  R --> O[Validate tenant user Runner Draft Conversation active]
  O --> W[Load state and evaluate stage]
  W --> K[Create three per-run SDK search tools]
  K --> P[Persist exact recommendation proof]
  P --> A[Validate final Card answer]
  A --> M[Ajv parse and Card mount]
  M --> G[Register exact payload]
  G --> D[Persist rendered/failed Delivery]
  D --> U[Explicit user action]
  U --> F[Refresh state]
  F --> C{Continuation?}
  C -->|yes| R
  C -->|no| M
~~~

The LLM clarifies, searches and proposes. Only explicit Card endpoints confirm, configure, install, bind or Finalize.

## PostgreSQL

The clean branch adds two tables: `nl2agent_session_t` with identity/lifecycle/revision/workflow/inline catalog, and `nl2agent_installation_operation_t` with idempotency key, checkpoint, lease, redacted result/error and timestamps. Existing Agent, Conversation, MCP, ToolInfo/ToolInstance and Skill/SkillInstance tables remain resource truth.

~~~mermaid
erDiagram
  AGENT ||--o{ NL2AGENT_SESSION : Runner
  AGENT ||--o| NL2AGENT_SESSION : Draft
  CONVERSATION ||--o| NL2AGENT_SESSION : owns
  NL2AGENT_SESSION ||--o{ INSTALLATION_OPERATION : checkpoints
  AGENT ||--o{ TOOL_INSTANCE : binds
  AGENT ||--o{ SKILL_INSTANCE : binds
  MCP ||--o{ TOOL_INFO : discovers
~~~

Recommendation batches and Delivery remain compact objects inside the Session workflow because they are read and revisioned with that aggregate. Exact columns are in `05_persistence_simplification.md`.

## Catalog and recommendation flow

Adapters capture normalized, redacted catalogs during Session start. Local and official provider failure blocks start; Registry and Community fail independently. A search Tool ranks a read-only slice. Before returning it calls Backend to create one exact ordered recommendation object. Card registration verifies equality and changes it from searched to presented. Apply/Skip/install only resolve through that object and the immutable catalog.

~~~mermaid
sequenceDiagram
  participant F as Frontend
  participant B as Backend
  participant S as SDK
  participant D as PostgreSQL
  F->>B: /agent/run
  B->>D: owned active Session + catalog
  B->>S: catalog + proof callback
  S->>S: stable top five
  S->>B: exact batch
  B->>D: revision-CAS recommendation
  S-->>B: observation
  B-->>F: final Card
  F->>B: register exact payload
  B->>D: mark presented
  F->>B: explicit action
~~~

## Installation

~~~mermaid
stateDiagram-v2
  [*] --> claimed
  claimed --> resource_creating
  resource_creating --> resource_created
  resource_created --> health_checking: MCP
  health_checking --> tools_discovering
  tools_discovering --> connected
  resource_created --> binding_skill: Skill
  binding_skill --> completed
  connected --> binding_tools: explicit bind
  connected --> binding_skipped: explicit skip
  binding_tools --> completed
  binding_skipped --> completed
  resource_creating --> failed
  health_checking --> failed
  tools_discovering --> failed
  binding_skill --> failed
  failed --> claimed: explicit retry
~~~

A short transaction advisory lock protects claim/renew/transition. A persisted lease, not a held DB connection, spans external I/O. Competing requests conflict; expired leases are reclaimable; completed results replay idempotently. Container creation is compensated if persistence fails. A persisted MCP is retained after later discovery failure so retry resumes. Secrets pass directly to existing credential/install calls and never enter the operation, workflow, catalog, log or response.

## Card, continuation and generation

Backend validates the full final assistant message before persistence; Frontend validates once after completion. Registration completes before actions activate. Rendered Delivery follows successful mount and registration. Only canonical output failures increment retry count. Action responses carry a typed continuation reason; the Provider refreshes and rechecks scope before hidden send. Only retries one and two auto-run.

~~~mermaid
flowchart LR
  C[Canonical Card schema] --> FV[Frontend generated schema/Ajv]
  C --> BV[Backend validator]
  P[FastAPI + Pydantic] --> O[Generated OpenAPI]
  O --> TS[Generated TypeScript]
  TS --> UI[Provider and Cards]
  X[contracts:check] --> C
  X --> O
  X --> TS
~~~

## Stack

| PR | Result | Flag |
|---|---|---|
| PR1 Core Workflow and Draft Builder | Session aggregate, identities, requirements, models, identity, review/Finalize, core Cards/Provider | off |
| PR2 Local Resources | local catalog/search/proof, strict config, atomic Tool/Skill Apply/Skip | off |
| PR3 Online Catalogs and Trusted Recommendations | Registry/Community/official adapters, MCP normalization/search, online Cards | off |
| PR4 Installation and Binding | PostgreSQL operations/leases, MCP/Skill saga, health/discovery/binding/recovery | off |
| PR5 Delivery, Recovery and Release | complete Delivery/retry/continuation/recovery, generated contracts, one migration, E2E, enablement | enabled only after merge |
