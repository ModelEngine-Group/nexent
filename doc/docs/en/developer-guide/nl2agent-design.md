# NL2AGENT Current Implementation: Design Changes and Code-Volume Analysis Against develop

> Analysis snapshot: 2026-07-23
>
> Current branch: `dyx/nl2a-branch-lite`
>
> Current commit: `56c0a79b7`
>
> Local develop baseline: `d1db1cf49`

This document replaces the previous v3 cutover-only description and answers four questions:

1. What was absent from `develop`, and what the current branch adds or changes.
2. Why the current NL2AGENT implementation uses this state, message, action, and installation design.
3. Where the code volume is concentrated, including the share of tests and generated contracts.
4. Which risks should be closed before merging into `develop`.

“Current implementation” means the final tree at `56c0a79b7`, not v1/v2 protocols that existed in intermediate commits and were later removed.

## 1. Executive summary

Local `develop@d1db1cf49` has no NL2AGENT routes, Session table, Action contract, Card contract, SDK search tools, or frontend Builder components. The branch adds a complete product path for turning natural-language requirements into an editable Draft Agent, not a single UI feature.

The final architecture is:

- PostgreSQL is authoritative for Sessions, workflow, catalog snapshots, Action receipts, and installation operations.
- The LLM organizes requirements, decides when to search, and emits constrained cards. It cannot directly commit trusted resource IDs, URLs, tenant identity, or credentials.
- SDK search tools first persist server-side recommendation proofs. Cards and later Actions must match those proofs.
- All card writes enter one Action Dispatcher and use `action_id + expected_revision` for idempotency and concurrency control.
- The backend buffers the complete assistant answer, parses cards, CAS-updates workflow, persists the message, and only then emits one structured SSE event.
- MCP installation, web Skill installation, and MCP Tool binding use a recoverable lease/checkpoint runner; external I/O does not hold database transactions.
- The frontend is embedded in the Agent configuration page. Historical cards recover from message metadata. Completed Sessions are read-only until the user explicitly enters revision mode.
- `finalize` updates the version-0 Draft Agent and completes the Session. It does not create a published Agent version or submit the Agent Repository review workflow.

The NL2AGENT-specific final diff contains 183 files and `+43,277/-1,284` lines. Tests add 13,251 lines and generated contracts add 8,805 lines; together they represent 51.0% of all added lines. Executable and deployment code adds 20,603 lines, with most complexity in backend state and resource orchestration.

## 2. Baseline, divergence, and counting scope

### 2.1 Git baseline

| Item | Commit | Relationship |
| --- | --- | --- |
| Local `develop` | `d1db1cf49` | Direct ancestor of the current HEAD |
| Current NL2AGENT HEAD | `56c0a79b7` | 35 commits ahead of local develop |
| `origin/develop` | `f0a4165f4` | Diverged from the current branch |
| Merge base of current branch and `origin/develop` | `c7a7ae505` | Baseline for the branch-only diff |

In the current repository:

- `develop...HEAD` is `0/35`: local develop has no unique commits and this branch has 35.
- `origin/develop...HEAD` is `3/30`: remote develop has 3 commits missing from this branch, while this branch has 30 NL2AGENT-specific commits.
- The branch must therefore incorporate those 3 remote-develop commits before merge, followed by refreshed statistics, tests, and conflict review.

### 2.2 Two diff scopes

Two scopes are retained so shared foundation work is not incorrectly attributed to NL2AGENT itself.

| Scope | Git range | Commits | Files | Added | Deleted | Changed lines |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Shared foundation changes | `develop..c7a7ae505` | 5 | 194 | 11,883 | 12,692 | 24,575 |
| NL2AGENT-specific final diff | `c7a7ae505..HEAD` | 30 | 183 | 43,277 | 1,284 | 44,561 |
| Entire branch against local develop | `develop...HEAD` | 35 | 344 | 55,106 | 13,922 | 69,028 |

The five shared commits cover legacy-chat Markdown compatibility, Planning Agent, main-Agent filtering, ContextItems/context-runtime refactoring, and the notification center. NL2AGENT directly reuses the newer context-injection and chat-rendering capabilities, but most notification-center code is not part of the NL2AGENT core.

File and line counts in the first two rows cannot be added directly because the same file can change in both phases and the final diff folds intermediate additions and deletions together.

All counts use physical lines from `git diff --numstat`. They include tests, documentation, JSON Schema, and generated TypeScript; they are not logical LOC or cyclomatic complexity.

## 3. Capability change map against develop

| Area | develop baseline | Current implementation |
| --- | --- | --- |
| Product entry | No conversational Agent Builder | Builder Chat embedded in Agent configuration, with create, recovery, read-only, and continued-editing flows |
| Agent execution | Ordinary `/agent/run` streaming | Adds `draft_agent_id` and validated Action Context; NL2AGENT buffers the answer and emits one structured event |
| Session | No NL2AGENT state | Draft, Builder Conversation, workflow, and catalog snapshot created in one transaction |
| Workflow | No dedicated state machine | Workflow schema v3, ten stages, revision CAS, and revision mode |
| Writes | Each business API handles its own mutation | Eleven actions share `POST .../actions` |
| Messages | Ordinary text and units | Adds `message_type`, `message_metadata`, Action receipts, and Card Envelopes |
| Search | No Builder search tools | SDK tools for local Tool/Skill, web MCP, and web Skill search |
| Recommendation trust | LLM text cannot be verified | Search results become proofs; cards and Actions validate resource sets and catalog hashes |
| MCP | Generic MCP management | NL2AGENT recommendation parsing, configuration, remote/container installation, discovery, binding, and skip flows |
| Web Skill | Generic Skill installation | Trusted catalog resolution, redacted configuration, recoverable installation, and Draft binding |
| Long-running work | No durable NL2AGENT execution state | Operation ID, fingerprint, lease, heartbeat, checkpoint, retry, and replay |
| Frontend cards | No NL2AGENT contract | Seven structured card types, Registry rendering, history recovery, and unified Action lifecycle |
| Contract governance | Handwritten frontend/backend types | Pydantic -> OpenAPI/JSON Schema -> generated TypeScript |
| Database | No related tables or message metadata | Two NL2AGENT tables, two message columns, and synchronized fresh-init/migration SQL |
| Operations | No cutover validation | v3 cutover guard, retention policy, structured metrics, and rollback constraints |

## 4. Design goals, non-goals, and authority

### 4.1 Goals

NL2AGENT turns natural-language requirements into a Draft Agent that remains editable in the normal configuration UI. It covers:

- confirmation of five requirement dimensions;
- selection of one primary model and up to four fallback models;
- recommendation and binding of local Tools and Skills;
- online MCP/Skill search, installation, and configuration;
- Agent display name;
- final review of description, prompt, welcome message, example questions, and runtime parameters.

### 4.2 Non-goals

The current implementation deliberately does not:

- create an Agent publication version automatically;
- submit an Agent Repository review automatically;
- allow the LLM to choose database primary keys, tenant/user identity, credentials, or arbitrary MCP URLs;
- silently refresh catalogs for an active Session;
- retain v2 workflow compatibility, card delivery/registration APIs, or browser-side fence parsing;
- use browser state, LocalStorage, or Redis to recover business workflow state.

### 4.3 Sources of authority

Authority is ordered as follows:

1. PostgreSQL Session, Draft configuration, Action receipt, and installation operation.
2. Backend Pydantic workflow/Card/Action contracts and the workflow stage evaluator.
3. Trusted recommendation proofs written through SDK search callbacks.
4. Frontend read-only Session projection and message metadata.
5. LLM output and temporary browser state.

The complete logical Session identity is:

```text
tenant_id + user_id + runner_agent_id + draft_agent_id + conversation_id
```

HTTP and Agent Run boundaries validate tenant, user, Draft, Conversation, and Builder runner. Structured message finalization and installation operations also use the complete identity. Some internal workflow CAS helpers still query by only `tenant_id + draft_agent_id` and depend on earlier owner checks; this falls short of the intended rule that every persistent write directly carries the complete identity. See Section 19.

## 5. Architecture and end-to-end flow

```text
Agent configuration page
  |
  |-- POST /nl2agent/session/start
  |     `-- Draft Agent + Builder Conversation + v3 Session + Catalog Snapshot
  |
  |-- POST /agent/run
  |     |-- validate complete Session/Runner/Conversation identity
  |     |-- inject YAML System Prompt + Current Session JSON
  |     |-- SDK search tools may persist a trusted recommendation batch
  |     |-- buffer the complete final_answer
  |     |-- backend parses fences and validates cards/search proofs
  |     |-- one transaction: workflow CAS + assistant message + metadata + final unit
  |     `-- emit exactly one nl2agent_message SSE event
  |
  `-- POST /nl2agent/session/{draft_agent_id}/actions
        |-- Action ID/fingerprint/revision/stage/proof validation
        |-- create or replay the user Action receipt
        |-- invoke model, local-resource, MCP, Skill, identity, or finalize service
        `-- next /agent/run carries validated Action Context
```

### 5.1 Session start

`backend/services/nl2agent_session_service.py` loads external catalogs before opening the creation transaction. In one database transaction it then:

1. creates a `draft_<8 hex>` Draft Agent;
2. creates a Builder Conversation titled `NL2AGENT - <draft>`;
3. initializes workflow schema v3 at revision 0;
4. persists an immutable catalog version/hash and normalized catalogs;
5. persists the complete Session identity.

If any transactional step fails, Draft, Conversation, and Session roll back together. If the tenant lacks a Builder Agent, the backend seeds one and validates that all three built-in search tools are available.

### 5.2 Ordinary user text

For direct text input, the backend first applies deterministic handling for requirement confirmation or revision intent, then persists the user message. Agent Run receives the current workflow projection as `Current Session` JSON in the System Prompt.

### 5.3 Turn after a card Action

A card click first calls the unified Action API. After success, the frontend converts the Action receipt into `nl2agent_action_context` and appends a visually user-authored Action message to `/agent/run`.

The backend reloads the receipt and validates action ID, action type, display text, and workflow revision. It replaces the model query with an internal JSON instruction and does not persist a duplicate user message. A forged frontend display string therefore cannot bypass the already-persisted Action result.

## 6. Session and database design

### 6.1 `nl2agent_session_t`

Core fields:

| Field | Purpose |
| --- | --- |
| `tenant_id/user_id` | Session owner |
| `runner_agent_id` | Tenant-scoped NL2AGENT Builder |
| `draft_agent_id` | Version-0 Agent being generated |
| `conversation_id` | Hidden Builder Conversation |
| `status` | `active/completed/abandoned` |
| `workflow_schema_version` | Only version 3 is accepted |
| `workflow_revision` | Optimistic-lock revision |
| `session_catalogs` | Version/hash and five catalog groups |
| `workflow_state` | v3 state-machine JSONB |

Database constraints include:

- uniqueness of `(tenant_id, draft_agent_id)`;
- uniqueness of `(tenant_id, conversation_id)`;
- a status enum check;
- `workflow_state.revision == workflow_revision`;
- only one non-deleted tenant Builder Agent named `nl2agent`.

### 6.2 `nl2agent_installation_operation_t`

The table persists recoverable execution state for MCP, web Skill, and MCP Tool-binding operations:

- server-derived `operation_id`;
- complete Session identity;
- secret-free `installation_key`;
- SHA-256 request fingerprint;
- `pending/running/completed/failed`;
- checkpoint, attempt, lease owner, and lease expiry;
- redacted result and error.

The unique key `(tenant_id, draft_agent_id, installation_key)` prevents concurrent duplicate operations for the same resource.

### 6.3 Conversation message extensions

`conversation_message_t` adds:

- `message_type`: `chat`, `nl2agent_action`, or `nl2agent_card`;
- `message_metadata JSONB`: Action receipt or Card Envelope.

History recovery no longer reparses Markdown and does not need a separate card-delivery table.

### 6.4 Lifecycle and cleanup

Current behavior:

- An `active` Session older than `NL2AGENT_ACTIVE_RETENTION_DAYS` is opportunistically changed to `abandoned` when another Session starts.
- An `abandoned` Session older than `NL2AGENT_ABANDONED_RETENTION_DAYS` is soft-deleted in bounded batches together with its Draft, resource instances, and Conversation data.
- A `completed` Session remains durable editing history for the Agent and is removed when the Agent is deleted, not by age.
- Active and abandoned retention default to 30 days. Cleanup batch size defaults to 100 and is capped at 500.

The code still defines `NL2AGENT_COMPLETED_RETENTION_DAYS` and a completed-cleanup repository helper, but the lifecycle service does not use them. Cleanup is also only triggered by Session start and has no independent scheduler. The configuration and operational semantics should be reconciled.

## 7. Workflow v3 state machine

`backend/agents/nl2agent_workflow.py` is the contract source and declares `WORKFLOW_SCHEMA_VERSION = 3`. Old versions are not converted; parsing a non-v3 state fails closed.

### 7.1 Core state

| State | Meaning |
| --- | --- |
| `revision` | Increments after every valid workflow mutation or assistant-message finalize |
| `revision_mode` | Routes targeted edits after reopening final review |
| `requirements_review` | `collecting/awaiting_confirmation/confirmed` plus five-field summary |
| `model_selection_confirmed` | Whether model selection was written to the Draft and confirmed |
| `recommendations` | Local/MCP/Skill search proofs and processing status |
| `mcp_workflows` | MCP install, discovery, and binding business results |
| `online_configuration_confirmed` | Whether all online-resource work is complete |
| `identity_confirmed` | Whether the display name is confirmed |

### 7.2 Stage decisions

| Stage | Expected card | Logical actions |
| --- | --- | --- |
| `requirements_collecting` | None; a requirements card may be generated once all fields exist | Clarify or generate summary |
| `requirements_confirmation` | No duplicate card | Confirm or revise requirements |
| `model_selection` | `model_selection` | Select models |
| `local_resource_search` | `local_resources` | Search local resources |
| `local_resource_review` | Local card if not yet presented, otherwise none | Apply or skip |
| `online_resource_search` | Unregistered `web_mcp/web_skill` types | Search online resources or continue configuring existing results |
| `online_resource_review` | Online cards not yet presented | Install, bind, skip, or complete the online phase |
| `agent_identity` | `agent_identity` | Save display name |
| `final_review` | `final_review` | Finalize the Draft |
| `revision_routing` | No fixed expected type | Route the requested edit to one configuration domain |

`evaluate_workflow()` is the single decision function shared by frontend state, System Prompt context, and backend stage validation.

### 7.3 Recommendation state

Each `RecommendationBatch` stores:

- `resource_type = local/mcp/skill`;
- `searched -> presented -> applying -> applied`, or `skipped/completed`;
- catalog version/hash;
- exact Tool IDs, Skill IDs, or online item keys;
- local selection and operation ID.

Search tools verify that the current stage allows the search before persisting proof. Atomic assistant-message finalization moves the matching batch from `searched` to `presented`. Local binding uses a reservation, and online batches become `completed` when the user explicitly completes online configuration.

### 7.4 MCP business state

Each MCP recommendation follows:

```text
configuration_required -> installing -> connected
                                      -> tools_bound
                                      -> binding_skipped
                                      -> failed
```

`connected` is still unresolved. The user must bind discovered Tools or explicitly skip binding before online configuration and finalization can complete.

## 8. Catalog snapshots and recommendation proofs

### 8.1 Catalog composition

Each new Session pins five groups:

1. `tool_catalog`: tenant-local `local/mcp/langchain` Tools, excluding built-ins.
2. `skill_catalog`: Skills already installed for the tenant.
3. `registry_results`: official MCP Registry entries.
4. `community_results`: community MCP entries.
5. `official_skills`: installable or resource-missing recoverable official Skills.

Failure to load local Tools/Skills or the official Skill catalog prevents Session start. Registry and community MCP providers degrade independently to an empty catalog plus a warning.

Budgets are explicit: each marketplace allows at most 20 pages, 2,000 items, 5 MiB, and 15 seconds. Local Tool and Skill catalogs are capped at 2,000 items each.

### 8.2 Canonicalization and content addressing

Session versions use `catalog_<32 hex>`. Before hashing:

- strings receive NFKC normalization and trim;
- dictionary keys are stably sorted;
- top-level catalog items are sorted by canonical JSON;
- nested arrays retain business order;
- the entire canonical payload receives SHA-256.

The backend recomputes the hash whenever it loads a snapshot. Any mismatch in content, version, or hash stops processing.

### 8.3 Proof binding

SDK search return values cannot declare trusted snapshot identity. The backend callback binds the current Session version/hash when it writes a recommendation batch. Validation repeats at three points:

- the assistant card parser requires the card resource set to exactly match the proof;
- the Action Dispatcher requires the batch to belong to the current workflow and snapshot;
- resource services revalidate that each selected ID/item key belongs to the batch.

A catalog change requires a new Session. Active Sessions are not silently refreshed, preserving equivalence between what the user saw and what the backend later executes.

## 9. SDK search-tool design

The Builder exposes only three built-in tools:

- `nl2agent_search_local_resources`;
- `nl2agent_search_web_mcps`;
- `nl2agent_search_web_skills`.

When building AgentConfig, the backend injects tenant, user, Draft, language, confirmation state, immutable catalogs, and the proof recorder. The SDK itself does not read environment variables or call backend HTTP services.

Search behavior is constrained:

- query strings receive NFKC, casefolding, stop-word filtering, and jieba segmentation for Chinese;
- names and metadata are fuzzily matched independently, with a minimum keyword score of 0.62;
- keyword matching uses OR semantics and includes coverage in the combined score;
- merged local Tool/Skill results are capped at 5;
- web MCP and web Skill results are capped at 5 each;
- batch IDs hash the Draft, normalized query, and exact result set;
- if proof persistence fails, the tool returns an error and the model cannot emit a trusted card.

The web MCP tool also normalizes Registry/community metadata into remote, container, or unsupported installation options. Configuration fields explicitly carry type, required status, and secret status.

## 10. Unified Action Dispatcher

All business mutations enter:

```http
POST /nl2agent/session/{draft_agent_id}/actions
```

Example:

```json
{
  "action": "apply_local_resources",
  "action_id": "uuid",
  "expected_revision": 18,
  "display_text": "Applied local resources",
  "payload": {
    "recommendation_batch_id": "local_xxx",
    "tool_ids": [1],
    "skill_ids": [2],
    "tool_config_values": {}
  }
}
```

The eleven actions are:

- `confirm_requirements`;
- `save_model_selection`;
- `apply_local_resources`;
- `skip_local_resources`;
- `install_mcp`;
- `bind_mcp_tools`;
- `skip_mcp_tools`;
- `install_web_skill`;
- `complete_online_configuration`;
- `save_identity`;
- `finalize`.

### 10.1 Validation order

The Dispatcher:

1. loads the Session through an owner-scoped query;
2. checks for an existing receipt with the same `action_id`;
3. requires an active Session;
4. validates `expected_revision`;
5. validates that the current stage allows the Action;
6. validates recommendation proof and catalog snapshot for resource Actions;
7. uses a PostgreSQL advisory lock to create one unique user Action message;
8. runs the domain service;
9. changes the receipt to applied/failed with a redacted result or error code.

### 10.2 Idempotency

The Action fingerprint is SHA-256 over canonical JSON for the complete request except `action_id`; it therefore includes action type, revision, display text, and payload.

- Same ID, same fingerprint, already successful: return `replayed` without repeating business work.
- Same ID, different fingerprint: return 409.
- Same ID with `failed`: allow a new claim.
- Same ID with `pending`: return `pending`.
- First successful execution: return `applied`.

The human-readable Action message is created once and maps one-to-one to the server receipt.

### 10.3 Payload trust boundary

Actions use a strict discriminated Pydantic union. The client cannot submit:

- tenant/user/runner/conversation identity;
- installation operation IDs;
- arbitrary MCP URLs;
- arbitrary Skill sources;
- Tools, Skills, or MCPs outside the recommendation batch.

The client only sends selections and configuration values allowed by the card. The backend resolves real resources from the Session catalog and database.

## 11. Card contracts, message persistence, and SSE

### 11.1 Contract source

`backend/consts/nl2agent_card.py` defines seven card types:

- requirements summary;
- model selection;
- local resources;
- web MCP;
- web Skill;
- Agent identity;
- final review.

The Pydantic contracts generate:

- `contracts/nl2agent-card.schema.json`;
- `contracts/nl2agent-openapi.json`;
- `frontend/contracts/generated/nl2agent-card.schema.json`;
- `frontend/contracts/generated/nl2agent-api.ts`.

### 11.2 Model serialization

The model still emits `nl2agent-*` fenced JSON, but only as an internal model-to-backend serialization format. The browser does not parse those fences and history does not replay them.

The backend parser processes the complete final answer and checks:

- complete fences, supported language tags, and valid JSON;
- strict payload types and length limits;
- matching Draft ID;
- no duplicate card type or key;
- exact equality between recommendation-card resources and trusted proof;
- exact card types required and allowed by the current stage.

Envelope:

```json
{
  "schema_version": 1,
  "draft_agent_id": 123,
  "workflow_revision": 19,
  "cards": [
    {
      "card_type": "local_resources",
      "card_key": "local_xxx",
      "payload": {}
    }
  ]
}
```

The Card Envelope does not include catalog version/hash. The frontend reads those identifiers from the recommendation batch in read-only Session state and never treats them as Action input.

### 11.3 Atomic finalization

Every NL2AGENT assistant answer uses one transaction:

1. load the active row with complete Session identity;
2. read the current revision;
3. parse the full answer and validate cards/proofs;
4. apply requirements, presentation, or revision-mode transitions;
5. increment revision;
6. CAS the workflow using complete identity;
7. persist one `message_type = nl2agent_card` assistant message;
8. persist the Envelope in `message_metadata.nl2agent_card`;
9. persist fence-free display text in message content and one final-answer unit.

Even a turn without cards becomes a structured message with an empty `cards` array and advances revision. Any failure rolls back all state, so no partial workflow or message survives.

### 11.4 SSE

NL2AGENT is not token-streamed. After Agent Run completes, the backend emits:

```text
type = nl2agent_message
content = persisted message_id/content/type/metadata/status
```

The frontend replaces its temporary message with the server message ID, reads the Envelope from metadata, and renders through the Card Registry. Ordinary Agents keep the existing streaming protocol.

## 12. Resource application and recoverable installation

### 12.1 Local Tool/Skill

Local application first requires selected IDs to be a subset of the recommendation batch, then reloads resources and parameter schemas from the database. Tool configuration validates type, choices, required fields, and secret rules.

One database transaction:

1. reserves the presented batch as applying with an operation hash;
2. upserts ToolInstance and SkillInstance;
3. marks the batch applied;
4. commits the revision transition.

Any failure rolls back the entire operation, preserving an externally visible “nothing applied” result.

### 12.2 Durable Installation Runner

MCP, web Skill, and MCP Tool binding share one runner:

- operation ID derived from complete Session identity, resource type, and installation key;
- PostgreSQL advisory and row locks serialize claims;
- default lease of 5 minutes and heartbeat every 60 seconds;
- stale-lease takeover;
- completed-operation replay;
- checkpoint recovery after external side effects;
- provider I/O outside short database transactions;
- fixed, redacted persisted error code/message.

Credentials may contribute to the request fingerprint input, but plaintext secrets are not stored in fingerprints, checkpoints, results, errors, logs, or responses. Checkpoint/result objects are recursively redacted by sensitive key.

### 12.3 MCP installation

Supported paths:

- Registry remote;
- Registry package converted to npx/uvx container configuration;
- community remote;
- community container;
- explicit rejection of unsupported metadata.

After installation, the service reloads the MCP record, connects through the secure transport, discovers Tools, persists the Tool catalog, and marks workflow state as connected. The user must then bind selected Tools or skip binding.

### 12.4 Web Skill installation

A Skill can only be resolved from the Session's official catalog. The backend reloads configuration schema and defaults. Secret defaults return `null`; unknown fields and type mismatches fail validation.

File installation, Skill-record parsing, and configuration binding each write checkpoints for retry. An official Skill with `resource_missing` is excluded from local results but remains available as an online recoverable item.

## 13. MCP network security

`backend/services/nl2agent_mcp_url_security.py` is the single network-policy entry point for remote NL2AGENT MCP traffic.

It:

- permits only HTTP/HTTPS;
- rejects embedded usernames/passwords;
- restricts ports to 1-65535;
- rejects loopback, link-local, unspecified, multicast, and reserved addresses;
- explicitly rejects common cloud metadata endpoints;
- resolves DNS and pins an allowed IP before connecting;
- preserves the original Host/SNI while TCP connects only to the validated IP;
- re-resolves and revalidates every redirect;
- uses `trust_env = false` and prevents callers from overriding transport, proxy, or certificate verification.

The current default differs by deployment path:

- a bare backend process defaults `NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS=true` in `const.py` when the variable is absent;
- Docker/Kubernetes generated configuration injects `false` by default;
- production deployments are therefore normally public-only, while direct local startup may permit private networks.

The default should be unified before merge so the same version does not expose different SSRF boundaries depending on how it starts.

## 14. Frontend design

### 14.1 Embedded configuration page

After Builder start, the Agent configuration page becomes three columns:

- Builder Chat;
- Agent Config;
- Agent Info.

Manual configuration on the right is disabled while the Session is active, preventing simultaneous browser-form and Builder writes. Successful Actions reload both the Agent and authoritative Session projection.

### 14.2 Session recovery

The page resolves a Session by `draft_agent_id` rather than LocalStorage. Chat history comes from the original Conversation:

- `nl2agent_action` becomes a read-only user Action message;
- `nl2agent_card` restores its Envelope from metadata;
- completed Sessions disable input and display a continue-editing control;
- resume enters revision mode.

### 14.3 Card Registry and lifecycle

`cardRegistry.tsx` is the only card-type-to-component mapping. Every card uses `useNl2AgentCardLifecycle` for:

- `crypto.randomUUID()` Action IDs;
- expected revision from authoritative Session state;
- Action-ID reuse for retry within the same mounted component;
- input locking during Actions;
- Session-state refresh after success;
- automatic next Agent Run except for intermediate installation steps and finalize.

MCP install, Tool binding, and Skill installation may occur multiple times in the online-resource stage. `OnlineConfigurationBar` supplies the Session-level complete-configuration action.

### 14.4 History and Markdown

The generic Markdown renderer no longer recognizes NL2AGENT fences. Structured cards only come from `message_type + message_metadata`, so history loading:

- does not register cards again;
- does not report delivery;
- does not automatically execute Actions;
- remains decoupled from ordinary Markdown code fences.

## 15. Finalize, completed Sessions, and revision mode

`finalize` performs one transaction:

1. require completed requirements, local resources, MCP work, online configuration, and identity;
2. revalidate that selected models remain available;
3. reload bound Tools/Skills and reject dangling references;
4. merge final-card description, prompt, and runtime parameters;
5. update the version-0 Draft Agent;
6. change the Session from active to completed.

It returns `status = draft_ready`. The service/function still uses the name `publish_agent`, and some frontend text says Publish, but no Agent version or marketplace publication side effect occurs.

Completed Session chat and cards are read-only. Resume is owner-only and requires:

- Draft and Conversation still exist;
- the catalog snapshot still passes hash validation;
- completed workflow is at final review;
- a successful CAS that reopens the Session as active, sets `revision_mode=true`, and increments revision.

The Prompt instructs revision mode to change only one configuration domain per turn. The backend currently only requires card types to belong to an allowed set and prevents duplicate types; it does not enforce a maximum of one distinct card type. The single-domain rule is therefore primarily a Prompt constraint rather than a server invariant.

## 16. HTTP APIs and error semantics

There are nine NL2AGENT routes:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/nl2agent/sessions` | List current user's active Sessions |
| GET | `/nl2agent/session/by-conversation/{conversation_id}` | Recover by Conversation |
| GET | `/nl2agent/session/by-agent/{draft_agent_id}` | Recover by Draft |
| POST | `/nl2agent/session/start` | Create Draft/Conversation/Session |
| POST | `/nl2agent/session/{draft_agent_id}/resume` | Continue editing |
| POST | `/nl2agent/session/{draft_agent_id}/abandon` | Abandon an active Session |
| GET | `/nl2agent/session/{draft_agent_id}/state` | Read authoritative projection |
| GET | `/nl2agent/session/{draft_agent_id}/web-skill/configuration` | Read trusted, redacted Skill configuration |
| POST | `/nl2agent/session/{draft_agent_id}/actions` | Unified business write entry |

Stable Action endpoint semantics:

| HTTP | Meaning |
| --- | --- |
| 401 | Unauthenticated |
| 403 | Owner/tenant/Draft is not accessible |
| 409 | Revision, stage, Session, Action fingerprint, or recommendation-proof conflict |
| 422 | Strict Action payload validation failure |
| 502 | Provider or connection failure |
| 503 | Action persistence or durable operation temporarily unavailable |

Lifecycle endpoints use application error-code mapping, where invalid requests are generally 400 and operation failures generally 500. The same domain exception category does not yet map uniformly to 400/422 or 500/503 across all NL2AGENT endpoints.

## 17. Observability, cutover, and rollback

### 17.1 Metrics

NL2AGENT records low-cardinality counters without sensitive labels:

- Action success/replay/pending/conflict/failure;
- workflow CAS conflict;
- installation retry/takeover/conflict/provider failure/heartbeat failure/replay/success;
- card parse success/failure;
- atomic message finalize success/conflict/failure;
- structured SSE sent/failure/stopped.

Labels do not contain tenant/user IDs, URLs, payloads, catalog content, error text, headers, tokens, or secrets.

### 17.2 v3 cutover

`deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql` performs an incompatible rebuild:

- soft-deletes legacy NL2AGENT Conversation/message data;
- drops old installation/session/catalog-snapshot tables;
- creates the current two tables and unique indexes;
- removes duplicate Builder Agents;
- does not convert old workflow payloads to v3.

Fresh deployment SQL in `deploy/sql/init.sql` is synchronized. Back up the database and run this guard before deployment:

```bash
source backend/.venv/bin/activate
python backend/scripts/check_nl2agent_cutover.py
```

The guard blocks non-v3 active Sessions, invalid catalog hashes, remaining `card_delivery/online_installations`, and Builder Conversations not bound to a v3 Session.

### 17.3 Rollback

- If no v3 Session has been created, stop traffic and deploy the previous application.
- Once v3 Sessions exist, the old binary cannot safely read them. Restore both the pre-cutover database snapshot and application version.
- Do not perform code-only rollback and do not force-push published history.

## 18. Code-volume distribution

### 18.1 NL2AGENT-specific file status

| Status | Files | Added | Deleted | Changed lines |
| --- | ---: | ---: | ---: | ---: |
| Added files | 113 | 38,604 | 0 | 38,604 |
| Modified existing files | 70 | 4,673 | 1,284 | 5,957 |
| Total | 183 | 43,277 | 1,284 | 44,561 |

There are no files finally deleted or renamed. Deletions of intermediate protocols are folded into the final net diff across the 30 commits.

### 18.2 By layer

| Layer | Files | Added | Deleted | Changed lines | Share of additions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Backend runtime | 55 | 13,181 | 515 | 13,696 | 30.5% |
| Tests | 50 | 13,251 | 19 | 13,270 | 30.6% |
| Generated contracts | 4 | 8,805 | 0 | 8,805 | 20.3% |
| Frontend runtime | 50 | 5,967 | 737 | 6,704 | 13.8% |
| SDK runtime | 11 | 1,256 | 9 | 1,265 | 2.9% |
| Documentation | 4 | 618 | 3 | 621 | 1.4% |
| Deployment/database | 9 | 199 | 1 | 200 | 0.5% |

`test/`, frontend `__tests__`/`*.test.*`, and deployment tests are grouped as Tests. Root contracts and frontend generated contracts are grouped as Generated contracts.

Executable and deployment code adds 20,603 lines and deletes 1,262. Tests plus generated contracts add 22,056 lines, or 51.0% of all additions. The branch is large, but roughly half of the volume is verification or contract derivation rather than handwritten runtime code.

### 18.3 By file type

| Type | Files | Added | Deleted | Share of additions |
| --- | ---: | ---: | ---: | ---: |
| Python | 98 | 25,808 | 540 | 59.6% |
| JSON | 7 | 6,977 | 49 | 16.1% |
| TSX | 27 | 4,635 | 582 | 10.7% |
| TypeScript | 19 | 3,120 | 106 | 7.2% |
| TSX tests | 6 | 1,173 | 0 | 2.7% |
| Markdown | 4 | 618 | 3 | 1.4% |
| TS tests | 6 | 405 | 0 | 0.9% |
| YAML | 4 | 210 | 0 | 0.5% |
| SQL | 3 | 183 | 0 | 0.4% |
| Other/Shell/TOML/Dockerfile | 9 | 148 | 4 | 0.3% |

Python contributes 59.6% of additions, reflecting that backend state, services, database code, and pytest suites contain most complexity. JSON is large mainly because of OpenAPI and Card Schema, not handwritten configuration.

### 18.4 Largest handwritten hotspots

| File | Added/deleted | Main responsibility |
| --- | ---: | --- |
| `backend/services/nl2agent_runtime_service.py` | `+1066/-0` | Production dependency assembly and facade |
| `backend/agents/nl2agent_session_catalog.py` | `+929/-0` | Workflow mutation, proof handling, resource completion |
| `backend/services/nl2agent_mcp_service.py` | `+897/-0` | MCP resolution, installation, discovery, binding |
| `backend/services/nl2agent_catalog_service.py` | `+734/-0` | Catalog loading, redaction, web Skill installation |
| `frontend/components/nl2agent/FinalizeCard.tsx` | `+704/-0` | Final configuration review and Draft finalization |
| `backend/services/nl2agent_action_service.py` | `+531/-0` | Unified Actions, idempotency, proof validation |
| `frontend/components/nl2agent/LocalResourcesCard.tsx` | `+513/-0` | Local resource selection and configuration |
| `backend/database/nl2agent_session_db.py` | `+509/-0` | Session repository, CAS, cleanup |
| `backend/consts/model.py` | `+507/-159` | Action request contracts and AgentRequest extension |
| `sdk/.../search_web_mcps_tool.py` | `+460/-0` | MCP metadata normalization and search |
| `backend/consts/nl2agent_card.py` | `+424/-0` | Card/Envelope Pydantic contracts |
| `frontend/components/nl2agent/WebMcpCard.tsx` | `+412/-0` | MCP installation and Tool-binding UI |

These 12 files add 7,686 lines, or 37.3% of handwritten executable/deployment additions. The first three backend orchestration files alone approach 2,900 lines and deserve the most focused review and future decomposition.

### 18.5 Tests and generated code

The 50 test files have a net diff of `+13,251/-19`:

- 37 Python files under `test/`: `+11,666/-17`;
- 12 frontend Vitest files: `+1,578/-0`;
- 1 deployment migration test: `+7/-2`.

Coverage includes Session/CAS, Action idempotency, catalog proof, Card parser, installation runner, MCP SSRF controls, publication/finalization, history recovery, frontend card lifecycle, and SQL migration.

Four generated contract files add 8,805 lines: OpenAPI 3,769; generated API TypeScript 2,020; and two Card Schema copies at 1,508 lines each.

## 19. Review findings and recommended design work

### 19.1 Close before merge

| Priority | Finding | Recommended design |
| --- | --- | --- |
| P0 | `origin/develop` has 3 branch-unique commits | Merge/rebase first; focus conflict review on sandbox/Skill lifecycle versus NL2AGENT MCP/Skill installation, then rerun all counts and tests |
| P0 | Bare-process MCP private-network default is true while Docker/Kubernetes default is false | Make the `const.py` default false; require explicit deployment opt-in for private networks and log the security decision |
| P0 | Most workflow mutations still use tenant + Draft CAS | Pass `Nl2AgentSessionIdentity` into `mutate_session_state`, proof writes, and resource transitions; remove the compatibility snapshot lookup |
| P0 | A `pending` Action receipt has no lease or stale reclaim | Add claim owner/expiry or reclaim based on message update time; reconcile domain state before safely replaying |
| P0 | Revision mode's one-domain-per-turn rule is not server-enforced | Limit `_validate_card_stage` to one card type in revision mode and add tests for text-only routing and multi-card rejection |

### 19.2 Next-stage convergence

| Priority | Finding | Recommended design |
| --- | --- | --- |
| P1 | `finalize/publish_agent/Review & Publish` naming conflicts with actual `draft_ready` behavior | If only the Draft is updated, rename consistently to finalize/apply; if publishing is required, call explicit version creation and separate permissions |
| P1 | Completed-retention constant/helper are unused and cleanup only runs on Session start | Remove dead configuration or add an independent scheduler; define observable retention for active, abandoned, and completed states |
| P1 | `Nl2AgentStaleCardError`, error code 030203, and a Redis CAS docstring remain from old protocols | Remove unused legacy symbols and update error text to prevent operational confusion |
| P1 | Catalog snapshots may approach several MiB and completed Sessions are retained indefinitely | Add snapshot-size metrics/database alerts; move to hash-deduplicated catalog-snapshot storage when scale requires it |
| P1 | Frontend strings mix Chinese and English literals | Move completed banner, OnlineConfigurationBar, Builder greeting, and configuration-page hints into locale files |
| P1 | Lifecycle and Action endpoints do not uniformly map 400/422 and 500/503 | Establish one NL2AGENT domain-exception-to-HTTP mapping and lock it in OpenAPI/tests |
| P2 | Cancellation of `run_blocking_installation` can wait on provider-thread `join()` | Use a cancellable provider client, bounded worker pool, or non-blocking reclamation so request cancellation cannot block the event loop |

### 19.3 Recommended implementation order

1. **Merge gate**: incorporate `origin/develop`; unify network defaults; complete full-identity CAS; add stale Action reclaim; enforce one-card revision mode.
2. **Protocol cleanup**: remove stale-card/Redis/retention remnants; align finalize and HTTP semantics.
3. **Operational hardening**: independent cleanup scheduler, snapshot-size metrics, installation cancellation and timeout.
4. **UX completion**: full i18n, browser-level end-to-end coverage, and recovery-oriented error messages.
5. **Scale path**: catalog deduplication, operation reconciliation jobs, and cross-Pod recovery drills.

## 20. Merge and acceptance checklist

### 20.1 Contracts and static checks

```bash
cd frontend
npm run contracts:check
npm run type-check
npm run lint
npm run format:check
```

### 20.2 Frontend tests

```bash
cd frontend
npm run test
```

At minimum verify card lifecycle, history recovery, completed resume, local configuration, web Skill configuration, and verification presentation.

### 20.3 Backend and SDK tests

```bash
source backend/.venv/bin/activate
pytest test/backend/agents/test_nl2agent_session_catalog.py -v
pytest test/backend/apps/test_nl2agent_app_errors.py -v
pytest test/backend/services/test_nl2agent_action_service.py -v
pytest test/backend/services/test_nl2agent_installation_runner.py -v
pytest test/backend/services/test_nl2agent_mcp_service.py -v
pytest test/backend/utils/test_nl2agent_card_validation.py -v
pytest test/sdk/core/tools/test_nl2agent_search_tools.py -v
pytest test/contracts -v
```

### 20.4 Database and cutover

```bash
source backend/.venv/bin/activate
pytest test/deploy/test_local_sql_migrations.py -v
bash deploy/tests/test_sql_migrations.sh
python backend/scripts/check_nl2agent_cutover.py
```

### 20.5 Required business scenarios

- full transaction rollback on Session start;
- same-Action replay, different-fingerprint conflict, and concurrent revision conflict;
- empty search-result cards;
- Action rejection after catalog hash mismatch;
- no echo of local Tool secret configuration;
- rejection of MCP redirects, DNS rebinding, and metadata endpoints;
- MCP/Skill installation failure, retry, lease takeover, and completed replay;
- atomic rollback of assistant message plus workflow;
- exact equality between one `nl2agent_message` SSE and history;
- completed read-only, resume, revision, and re-finalize;
- fail closed when any tenant/user/runner/Draft/Conversation field mismatches;
- Draft-ready only after finalize, with no unexpected publication version or marketplace side effect.

## 21. Primary implementation locations

| Responsibility | File |
| --- | --- |
| HTTP and error mapping | `backend/apps/nl2agent_app.py` |
| Production facade/dependency assembly | `backend/services/nl2agent_runtime_service.py` |
| Session initialization | `backend/services/nl2agent_session_service.py` |
| Lifecycle | `backend/services/nl2agent_session_lifecycle_service.py` |
| Workflow contract/evaluation | `backend/agents/nl2agent_workflow.py` |
| Workflow mutation/proof | `backend/agents/nl2agent_session_catalog.py` |
| PostgreSQL Session/CAS | `backend/database/nl2agent_session_db.py` |
| Action Dispatcher | `backend/services/nl2agent_action_service.py` |
| Card contract/parser | `backend/consts/nl2agent_card.py`, `backend/utils/nl2agent_card_validation.py` |
| Atomic assistant-message persistence | `backend/services/nl2agent_message_service.py` |
| Catalog snapshot/hash | `backend/utils/nl2agent_catalog_snapshot.py` |
| Catalog and web Skill | `backend/services/nl2agent_catalog_service.py` |
| Local resources | `backend/services/nl2agent_resource_service.py` |
| MCP | `backend/services/nl2agent_mcp_service.py` |
| Durable runner | `backend/services/nl2agent_installation_runner.py` |
| MCP URL security | `backend/services/nl2agent_mcp_url_security.py` |
| Finalize | `backend/services/nl2agent_publication_service.py` |
| Session projection | `backend/services/nl2agent_workflow_service.py`, `backend/services/nl2agent_summary_service.py` |
| SDK search tools | `sdk/nexent/core/tools/nl2agent/` |
| Frontend workflow | `frontend/components/nl2agent/Nl2AgentWorkflowContext.tsx` |
| Card Registry | `frontend/components/nl2agent/cardRegistry.tsx` |
| Frontend Action lifecycle | `frontend/components/nl2agent/useNl2AgentCardLifecycle.ts` |
| Chat/SSE adapter | `frontend/app/[locale]/newchat/adapter/remote-chat-model-adapter.ts` |
| Contract generation | `backend/scripts/export_nl2agent_openapi.py`, `frontend/scripts/sync-nl2agent-contracts.mjs` |
| v3 cutover guard | `backend/scripts/check_nl2agent_cutover.py` |

## 22. Overall assessment

Against develop, NL2AGENT moves from “LLM-generated UI text” to a database-authoritative, contract-driven, recoverable-execution architecture. Its strongest design choice is to put model output, user Actions, and external installation behind server-side proofs, revisions, and durable receipts. That substantially reduces duplicate execution, cross-Session resource references, unrecoverable history, and frontend/backend parsing drift.

The merge risk is not missing functionality but cross-layer volume plus a few constraints that are not yet fully server-enforced: complete-identity CAS, recovery of pending Actions, one-card revision routing, and consistent network defaults. Closing those P0 items first, followed by naming, retention, legacy-protocol cleanup, and i18n, would give the implementation a much clearer long-term maintenance boundary.
