# Runtime compatibility matrix

This is an opt-in architecture spike, not a production parity certification. “Live” means an actual configured model/tool/application path; “unit” is not substituted for live proof.

| Capability | Experimental native status | Evidence / boundary |
|---|---|---|
| Default CodeAgent / invalid selection | Verified, unit and deployed comparison | Default constructor retained; invalid/empty/case-invalid configuration fails |
| Native direct existing tools | Verified live | Existing ListDirectoryTool, valid schemas, IDs and individual results |
| Multiple calls and mixed content | Unit verified; live mixed paths observed | Indexed stream fragments, batch ordering and correlated errors |
| Native provider history | Verified live | Actual assistant tool_calls and tool role/tool_call_id; separate transcript avoids upstream textual memory |
| Streaming / final answers | Verified live API and browser | Existing observer stream and final reclassification; native content is never parsed as an action |
| Optional restricted Python | Verified live | Restricted local and strict Docker variants; actual 323 output |
| Stateful Python variables | Unit verified | Counter 40 -> 42 across code calls; independent real state-continuation workload remains unverified |
| Python -> authorized tools | Verified live | Both local functions and authenticated Docker bridge; child tool span belongs to code_execution |
| Hybrid / multiple steps | Verified live | Direct tool -> Python/programmatic tool -> model continuation -> final answer |
| MCP protocol/tool adapter | Verified live | Case-owned actual MCP stdio server, Nexent managed session/factory and real model call |
| Dynamic MCP containers | Unverified | Existing management layer reused without changes; no full container-registration business journey |
| Managed agents | Verified live | Native parent delegates; native child invokes Python and returns actual result |
| Definitions / switching | Verified live | Same persisted test Agent runs under both selections; full API definition hash unchanged across switching |
| Context selection and budgets | Unit verified; short deployed run verified | Authorized static items/history use existing context manager |
| Native current-run compaction | Unsupported | Transcript is atomic request tail; explicit overflow failure rather than splitting tool exchanges |
| Provider transient retries | Unit verified | Shared classifier/backoff/Retry-After; authentication fails fast; no tool execution before response acceptance |
| Cancellation / resource release | Verified unit and live | Real stream cancelled after a provider chunk; closer called; no second request; no pending closers |
| Maximum steps | Verified unit and live | One-step limit makes one inference and no unbudgeted fallback |
| Tool error recovery | Verified unit and live | Missing directory error followed by successful actual listing, with correlated IDs |
| Planning | Implemented, unit verified | Existing plan tools, callbacks and persistence; full live Redis/browser journey unverified |
| Verification / guardrails | Implemented, unit verified | Input and resolved programmatic argument checks, output masking, final repair and observer verification event |
| Clarification | Implemented, unit verified | Existing validated form and terminal HUMAN_INTERACTION event; browser answer/resume journey unverified |
| Qwen / DeepSeek / GLM / MiniMax native tools | Verified live | Discovered IDs in host-sdk-matrix.json; results used in final answers |
| Native reasoning | Evidence bounded | Qwen/GLM controls and reasoning fields verified; DeepSeek and MiniMax fields vary across gateway runs. Final observations do not establish reliable thinking control for every route |
| Provider continuation metadata | Implemented for reasoning/reasoning_content | Other provider-specific/encrypted reasoning structures unverified |
| Multimodal messages/results | Unverified / incomplete projection | Initial native memory projection currently retains text blocks; do not use this spike for multimodal workloads |
| NL2Agent / NL2Skill authoring | Intentionally remains CodeAgent | Platform prompts carry closed authoring/save protocols; ordinary user Agents select the configured runtime |
| Final branch images | Verified separately by D5 | Immutable image IDs and installed-source hash; no backend/SDK source overlay |

No schema migration or frontend runtime selector was introduced. Existing authored CodeAgent formatting instructions are retained verbatim and may be incompatible; only catalog-owned execution policies are replaced automatically. Return to CodeAgent and restart the runtime to roll back.
