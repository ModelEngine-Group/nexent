# NL2AGENT Design

NL2AGENT is a conversational builder embedded in the agent configuration page. It is not exposed in the ordinary agent or conversation lists.

## Session Authority

Each session binds a draft agent, the internal runner agent, and a conversation. PostgreSQL is the only authority for the session row, immutable normalized and redacted catalogs, and workflow JSONB. Workflow writes use a strictly increasing revision CAS. Session start creates the Draft Agent, internal conversation, and session in one transaction.

External installations are represented by `nl2agent_installation_operation_t`. The operation stores a secret-free request fingerprint and installation key, checkpoint, attempt count, lease owner and expiry, result references, and redacted errors. Completed operations replay idempotently; live lease conflicts are rejected; expired leases can be taken over. Provider I/O never holds a database connection. Redis is not used for NL2AGENT state, catalogs, installation locks, or recovery.

Old sessions and their internal Builder conversations are soft-deleted during migration and bounded cleanup. Existing Draft Agents remain available, but an old Builder conversation is never restored.

## Trust Boundaries

The model can only propose fenced JSON cards in a completed assistant message. The frontend validates the shared Card Schema, verifies the active Session-scoped draft identity, and reports delivery through the coordinator. Backend registration accepts only the latest complete assistant message and trusted recommendation proofs. Secrets never enter catalogs, logs, operation results, or responses.

## Frontend Coordinator

`Nl2AgentWorkflowProvider` is the unique Session-scoped coordinator. It owns scope checks, complete-message parsing, card registry delivery, action serialization, input blockers, session-state refresh, hidden continuations, recovery, and the two-attempt continuation retry limit. `Nl2AgentFenceRenderer` only parses completed fences and dispatches the card registry. Card components own presentation, forms, and explicit user actions. Historical and completed read-only messages never trigger side effects.

Nine fence tags map to seven logical card families: requirements, model selection, local resources, online MCP, online Skill, identity, and final review. Singular and plural online tags remain protocol-compatible aliases.

## Lifecycle

The workflow covers requirements, confirmation, model selection, local resources, online recommendations, identity, and final review. Finalize persists the complete Draft configuration and closes the active session. Users can continue editing from the configuration page or resume a completed final-review session; resume opens revision mode without restoring an old Builder chat.
