# Runtime and LLM layout preparation

This change relocates existing implementations before the planned NativeAgent work.
It preserves CodeAgent behavior and the installed smolagents version. It adds no
NativeAgent engine, execution-mode selector, model profile registry or HTTP sender.

## Implementation ownership

| Previous location | Canonical implementation |
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

## Public and internal imports

`agents/core_agent.py` explicitly exports only `CoreAgent`. The public agents
package retains its lazy export of the same class. The entry point does not alias
an implementation module in `sys.modules`; implementation helpers and dependency
patch targets belong to `execution/code/legacy_agent.py`. NexentAgent imports
CoreAgent through the public entry and its formatting helper from the implementation.

The four old internal modules in the table above have been removed. Resource and
LLM imports and test patch targets use their canonical paths. Direct users of these
old internal paths must update their imports; old serialized internal module paths
are no longer supported. No compatibility files remain for these internal modules.
The gateway modality aggregation remains a public export and preserves adapter
registration. Package discovery does not eagerly load Agent implementations.

Tests cover public class identity in both import orders, rejection of removed
internal paths, lazy package loading, canonical registration and serialization,
and the existing resource and Agent behavior.

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
