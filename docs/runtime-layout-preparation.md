# Runtime and LLM layout preparation

This change relocates existing implementations before the planned NativeAgent work.
It preserves CodeAgent behavior and the installed smolagents version. It adds no
NativeAgent engine, execution-mode selector, model profile registry or HTTP sender.

## Implementation ownership

| Existing import | Canonical implementation |
| --- | --- |
| `nexent.core.agents.core_agent` | `nexent.core.agents.execution.code.legacy_agent` |
| `nexent.core.agents.managed_mcp` | `nexent.core.agents.resources.managed_mcp` |
| `nexent.core.agents.tool_user_context` | `nexent.core.agents.resources.tool_user_context` |
| `nexent.core.gateway.modality.llm.llm_adapter` | `nexent.core.gateway.llm.adapter` |
| `nexent.core.gateway.modality.llm.openai` | `nexent.core.gateway.llm.providers.openai` |

The existing CoreAgent class still inherits CodeAgent. Its execution loop,
protocol parsing, logging, verification, sandbox integration and context handling
remain in the relocated implementation. The existing LLM adapter still wraps the
same OpenAI models and uses the existing transport and adapter registry.

## Compatibility

Old module paths alias the canonical module in `sys.modules`. They do not copy
classes or functions into a second implementation. Both paths therefore share
class identity, mutable module state and monkeypatch lookup sites. Existing
serialized references to old class paths can still resolve through those imports.
New internal resource and gateway aggregation imports use the canonical paths.

The new execution and resources package initializers do not load implementations.
The public agents package retains lazy exports. The gateway retains its existing
built-in adapter registration lifecycle; importing a legacy LLM alias does not
register a duplicate adapter.

Tests that intentionally load source files with isolated dependencies now load
the canonical physical file and use its new package depth. Their behavior
assertions remain intact. Import compatibility is tested separately in fresh
Python processes in both import orders.

## Next development steps

The future CoreAgent composition facade can be built at the existing public entry
while the legacy loop stays under `execution/code/`. A Native engine can then be
added as a separate implementation. Shared resource factories can be extracted
from NexentAgent without relocating these resource helpers again. Generation-model
request/response contracts and provider-specific preparation can be developed
under `gateway/llm/` alongside the existing adapters.

The current context manager, business tools, other modalities, model implementations,
backend API, frontend and database layout are unchanged by this preparation.
Reverting this change needs no data migration.
