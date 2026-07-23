# NL2AGENT v3 Design and Cutover Runbook

> This document describes the current NL2AGENT implementation. v2 Sessions, browser-side Markdown-fence card parsing, card delivery/registration APIs, and hidden continuation sentinels are not supported.

## 1. Purpose and trust boundary

NL2AGENT is a conversational Builder embedded in the Agent configuration page. It covers requirements confirmation, model selection, local Tool/Skill binding, online MCP/Skill installation, identity configuration, and Draft finalization.

The non-negotiable constraints are:

- PostgreSQL is the only authority for Sessions, workflow, catalogs, and installation operations.
- Browser state, LocalStorage, and Redis are not recovery or concurrency authorities.
- The model cannot choose arbitrary tenants, users, resource IDs, credentials, or MCP URLs.
- Every write is bound to the complete Session identity and checked against the current stage, recommendation proof, and revision CAS.
- Provider I/O never holds a database transaction.
- Finalize updates the Draft Agent; it does not automatically publish a version.

The complete Session identity is:

```text
tenant_id + user_id + runner_agent_id + draft_agent_id + conversation_id
```

Any mismatch fails closed.

## 2. Current end-to-end protocol

```text
Configuration page
  ├─ POST /nl2agent/session/start
  │    └─ Draft + Builder Conversation + v3 Session (one transaction)
  ├─ POST /agent/run
  │    ├─ SDK search tools persist trusted recommendation proofs
  │    ├─ the model completes one assistant answer
  │    ├─ the backend-only parser validates cards
  │    ├─ workflow CAS + message + metadata + unit (one transaction)
  │    └─ one nl2agent_message SSE event
  └─ POST /nl2agent/session/{draft_agent_id}/actions
       └─ Dispatcher → domain service → action receipt → next /agent/run
```

The model still uses controlled `nl2agent-*` fenced JSON as an internal model-to-server serialization format. The browser never receives or parses those fences. The backend parses only the complete final answer, validates it, and strips the fences from display text.

## 3. Session lifecycle

Lifecycle endpoints remain separate from business actions:

| Endpoint | Purpose |
|---|---|
| `POST /nl2agent/session/start` | Create the Draft, hidden Builder Conversation, and v3 Session |
| `POST /nl2agent/session/{draft_agent_id}/resume` | Enter revision mode for a resumable Session |
| `POST /nl2agent/session/{draft_agent_id}/abandon` | Abandon an active Session |
| `GET /nl2agent/session/{draft_agent_id}` | Read the public Session summary |
| `GET /nl2agent/session/{draft_agent_id}/state` | Read the authoritative Draft/workflow projection |

Session status is `active`, `completed`, or `abandoned`. Only active Sessions accept business actions. Completed history is read-only until resume reopens editing.

Session creation stores a normalized, redacted resource catalog in `session_catalogs`. Runtime state and catalogs are never recovered from Redis.

## 4. Workflow v3

`backend/agents/nl2agent_workflow.py` is the workflow contract source. The current `WORKFLOW_SCHEMA_VERSION` is 3.

v3 retains requirements review, model confirmation, recommendation batches, MCP business results, online configuration confirmation, identity confirmation, revision mode, and a monotonically increasing revision.

v3 removes:

- `card_delivery`;
- `online_installations`;
- card registration, delivery, and retry state;
- installation leases from workflow JSONB.

Card expectations are derived from business state. For example, a recommendation moves atomically from `searched` to `presented` when its persisted structured message is finalized. Installation execution state belongs to `nl2agent_installation_operation_t`.

v2 workflow is not migrated automatically. Pydantic validation rejects every non-v3 payload.

## 5. Unified Action Dispatcher

All business writes use:

```http
POST /nl2agent/session/{draft_agent_id}/actions
```

Request:

```json
{
  "action": "apply_local_resources",
  "action_id": "uuid",
  "expected_revision": 18,
  "display_text": "Applied local resources",
  "payload": {}
}
```

Response:

```json
{
  "action_id": "uuid",
  "action": "apply_local_resources",
  "status": "applied",
  "workflow_revision": 19,
  "result": {}
}
```

Supported actions:

- `confirm_requirements`
- `save_model_selection`
- `apply_local_resources`
- `skip_local_resources`
- `install_mcp`
- `bind_mcp_tools`
- `skip_mcp_tools`
- `install_web_skill`
- `complete_online_configuration`
- `save_identity`
- `finalize`

Response status is `applied`, `pending`, or `replayed`. Payloads are strict discriminated Pydantic models. Clients cannot provide tenants, credentials, arbitrary MCP URLs, or installation operation IDs.

The `action_id` receipt is stored in `conversation_message_t.message_metadata`. The same fingerprint can replay within the Session. Reusing an ID with a different fingerprint returns `409`. Human-readable `display_text` is persisted once.

Error semantics:

| HTTP | Meaning |
|---|---|
| 401/403 | Authentication or tenant/user/Draft/Conversation mismatch |
| 409 | Revision CAS, stage, Session status, or action fingerprint conflict |
| 422 | Action payload violates its contract |
| 502/503 | MCP/Skill provider or durable operation failure |

The removed fine-grained requirements/model/resource/MCP/Skill/identity/finalize write endpoints have no deprecated adapter.

## 6. Card Envelope, persistence, and SSE

`backend/consts/nl2agent_card.py` is the contract source for:

- `contracts/nl2agent-card.schema.json`
- `contracts/nl2agent-openapi.json`
- `frontend/contracts/generated/*`

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

Allowed card types are requirements summary, model selection, local resources, web MCP, web Skill, agent identity, and final review.

`backend/utils/nl2agent_card_validation.py` is the only parser. It processes a complete answer and validates Draft identity, revision, type/key uniqueness, strict payloads, count limits, recommendation batches and exact resource proofs, complete fences, and JSON validity.

`finalize_nl2agent_message` performs one transaction:

1. validate the complete Session identity and current revision;
2. parse and validate the cards;
3. apply inseparable presentation transitions;
4. CAS-update the v3 workflow;
5. write one assistant message with `message_type = "nl2agent_card"`;
6. write the Envelope to `message_metadata.nl2agent_card`;
7. write only fence-free display text to `message_content` and one final-answer unit.

Any failure rolls back the entire transaction. No partial message or workflow update remains.

NL2AGENT is not token-streamed. Success emits exactly one `nl2agent_message` SSE event matching the persisted message. Ordinary Agents retain their existing streaming behavior.

The frontend reads the Envelope from message metadata and renders through `cardRegistry.tsx`. History is read-only: loading it does not register cards, report delivery, or execute actions. The generic Markdown renderer handles only ordinary Markdown fences.

## 7. Durable Installation Runner

MCP and web Skill installations share `backend/services/nl2agent_installation_runner.py`:

- server-derived operation ID;
- request fingerprint;
- claim, lease owner/expiry, and heartbeat;
- secret-free checkpoint;
- retry, stale-lease takeover, and completed replay;
- redacted result and error persistence.

`nl2agent_installation_operation_t` uses `pending`, `running`, `completed`, and `failed`. Claims and transitions use short database transactions. Network, container, marketplace, and provider calls run outside transactions.

Credentials are runtime-only request input. They are not stored in plaintext fingerprints, checkpoints, results, errors, logs, or responses.

## 8. MCP network policy

`backend/services/nl2agent_mcp_url_security.py` is the only URL/DNS/redirect policy entry point. Initial connections and every redirect revalidate scheme, port, and resolved addresses, including DNS-rebinding, loopback, link-local, and metadata endpoint protections.

`NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS` is read only in `backend/consts/const.py`. Private networks are allowed by default. Explicit `false` permits public addresses only. MCP services do not duplicate this policy.

## 9. Observability

NL2AGENT metrics use low-cardinality, secret-free labels:

- action success, replay, pending, conflict, and failure;
- workflow CAS conflict;
- installation retry, lease takeover/conflict, provider/heartbeat failure, replay, and success;
- card parse success/failure;
- atomic finalize success/conflict/failure;
- structured SSE sent/failure/stopped.

Metrics never include tenant/user IDs, URLs, payloads, catalog content, error text, headers, tokens, or secrets. Logs, responses, and operation persistence follow the same rule.

## 10. v3 cutover runbook

This is an incompatible cutover. There is no v2 conversion and no deprecated adapter.

Before cutover:

1. Stop new NL2AGENT Sessions and write traffic.
2. Back up PostgreSQL and record the current application commit and image.
3. Inventory every non-v3 Session and Builder Conversation; identify Draft Agents that must remain.
4. Soft-delete legacy Session and internal Conversation/message/unit/source records. Do not delete Draft Agents that users need to keep.
5. Run the read-only guard:

```bash
source backend/.venv/bin/activate
python backend/scripts/check_nl2agent_cutover.py
```

The command returns non-zero when:

- an active Session is not schema v3;
- workflow state still contains `card_delivery` or `online_installations`;
- an NL2AGENT Builder Conversation is not bound to a non-deleted v3 Session;
- PostgreSQL cannot be inspected.

For cleanup, first write target Session/Conversation IDs to a temporary table and verify counts. Apply `delete_flag` updates in one transaction under database-administrator control and retain the audit record.

After cutover, verify start, action replay/conflict, installation recovery, one `nl2agent_message`, read-only history, resume, finalize, abandon, and tenant isolation.

## 11. Push and rollback

After backend, frontend, contract, and cutover checks pass, push the branch once:

```bash
git push origin dyx/nl2a-branch-lite
```

Do not create a PR and do not dual-write the old protocol.

Rollback rules:

- If no v3 Session has been created, stop traffic and deploy the pre-cutover application commit.
- Once v3 Sessions exist, the old binary cannot read them. Stop writes and restore both the pre-cutover database snapshot and application version. A code-only rollback is unsafe.
- Do not force-push or rewrite published history. Use deployment rollback or an explicit revert, then rerun the cutover guard.

## 12. Primary implementation locations

| Responsibility | File |
|---|---|
| HTTP and error mapping | `backend/apps/nl2agent_app.py` |
| Action Dispatcher | `backend/services/nl2agent_action_service.py` |
| v3 workflow | `backend/agents/nl2agent_workflow.py` |
| PostgreSQL state/CAS | `backend/agents/nl2agent_session_store.py` |
| Atomic message finalize | `backend/services/nl2agent_message_service.py` |
| Card contract/parser | `backend/consts/nl2agent_card.py`, `backend/utils/nl2agent_card_validation.py` |
| Installation runner | `backend/services/nl2agent_installation_runner.py` |
| MCP URL security | `backend/services/nl2agent_mcp_url_security.py` |
| Structured frontend event/Registry | `frontend/lib/chat/nl2agentCardEvent.ts`, `frontend/components/nl2agent/cardRegistry.tsx` |
| Cutover guard | `backend/scripts/check_nl2agent_cutover.py` |
