# Compatibility boundaries

| Capability | Current status / evidence boundary |
|---|---|
| Default CodeAgent construction | Preserved; relevant legacy unit regression |
| Native selection | Only declared tool support; per-model parent/child factory selection |
| No tool support / unknown | CodeAgent compatibility fallback, no provider-error downgrade |
| No reasoning support / unknown | Profile controls remain authoritative; no replacement ReAct-thinking instruction |
| Direct native / Python / programmatic / hybrid | Real model-service local/Docker matrix |
| Structured history, IDs and reasoning continuation | Model service contracts; real-model and adapter checks |
| Completion reason, malformed/incomplete output | Unit and controlled real HTTP/SSE integration |
| Public staged text / retry / final promotion | Observer, backend persistence and frontend live/history projection checks |
| MCP / managed native child / cancellation | Representative real-runtime verification |
| NL2Agent/NL2Skill | Deliberately pinned to CodeAgent authoring protocols |
| Native current-run compaction | Unsupported: explicit budget overflow failure; history is not silently textualized |
| Initial multimodal memory projection | Incomplete; inherited experimental limitation |
| Dynamic MCP container business journey, concurrent child lifetime, live plan/verifier/clarification business round trips | Not established by this change; focused unit proof is distinct from full journey acceptance |

This opt-in feature does not claim universal model or full production/harness parity. Provider-returned reasoning evidence is separate from declared capability, requested controls and native tool support. Missing reasoning output is unverified, not a success inferred from tool execution.
