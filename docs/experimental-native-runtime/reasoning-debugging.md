# Provider reasoning and output-budget debugging

Use the Phoenix **default** project at http://localhost:6006. Provider reasoning and public assistant text are separate fields/events. Seeing reasoning in Phoenix proves the provider/model-service path preserved it; seeing it in chat additionally requires the native adapter to forward typed reasoning events.

## Verify the original GLM response

Open [the greeting LLM span](http://localhost:6006/projects/UHJvamVjdDox/traces/cd2c7e6a090c229293e5dec2878d5753?selectedSpanNodeId=U3Bhbjo0). Select **glm-5.3.generate**, inspect **Output**, and expand `reasoning_parts` → the text part's `text`. `content_parts` is the public answer. The normalized message ID is `b5a06655-fcf9-439a-ae63-9426459a582b`. Usage reports 90 output tokens, including 45 reasoning tokens, with `finish_reason=stop`.

## Diagnose chat 2's length error

Open [the failed LLM span](http://localhost:6006/projects/UHJvamVjdDox/traces/5caff80738ef19ad56cf27379c012083?selectedSpanNodeId=U3Bhbjo4). Its containing Agent spans carry `conversation.id=2` and `session.id=2`.

1. Inspect **Input** to confirm the assembled instructions, recent history, and current user request. This request asked for a complex code-executor demonstration.
2. Inspect span attributes `llm.invocation_parameters`: the resolved request contains `max_output_tokens: 4096`. Model capacity is not the same as this per-generation allowance.
3. Inspect **Output**: `finish_reason` is `length`, `content_parts` is empty, `tool_calls` is empty, and `reasoning_parts` contains provider planning text. Do not infer a successful final answer from that partial reasoning.
4. Compare `usage` in Output or `llm.usage.*` attributes / `model_usage` event:

   | Counter | Provider-reported value |
   |---|---:|
   | Input tokens | 3739 |
   | Output tokens | 4096 |
   | Reasoning tokens | 4096 |
   | Total tokens | 7835 |
   | Cached input tokens | 3520 |

5. Inspect **Events** / exception details and follow the parent Agent span. The provider ended the generation at its requested output limit; native completion validation then rejected it before any tool execution or final acceptance.

The configured outlet has a 1,000,000-token context window and a 131,072-token maximum output capacity. Its default output reserve is unset. `capacity_resolver.py` therefore selects the 4096 default; the context budget snapshot carries that value, and `LegacyInvocationOptions` passes it to the model-service request. All 4096 generated tokens in this incident were reasoning. A short visible chat or low context-usage percentage does not rule out exhausting the output allowance.

To change the allowance deliberately, use **Model Configuration → edit glm-5.3 → Advanced/capacity → Output Reserve** (Chinese: **输出预留Token数**). Choose an allowance within the configured model/provider limits. This is distinct from **Max Output Tokens**, which describes capacity. A smaller task or lower supported reasoning effort can also reduce the work needed. The GLM profile does not promise a thinking-off control; do not assume one. This fix does not silently increase any saved budget or model setting.

## What the native adapter now preserves

- Provider `reasoning_delta` is forwarded as `model_output_deep_thinking`, with attempt and step identity, on both experimental branches. Public `text_delta` continues as plain `model_output`.
- Completion-only text/reasoning is emitted when no deltas were received, without duplicating streamed output or replaying reasoning as a final answer.
- Native model-service calls reuse response reset, retry/cached-usage diagnostics and terminal error conversion. Narrow read-only wrapper accessors expose finish/cache values to the existing token-event consumer. Cancelled/failed attempts retain rollback behavior.
- Length errors remain failures and include available requested/output/reasoning counters. No partial tools execute and no truncated text is marked final.
- The existing chat renderer displays reasoning separately; live and saved-history adapter tests verify that separation. No frontend product change was needed.

Fresh deployed GLM/Python trace: `2026f23891c47866b40d5c7725a0d16a`; Qwen/Python trace: `d3093a01e3cbff593be04ccd98a688e9`; browser GLM trace: `d416f2b950ddb1457724cd9dacec091a`. The actual browser showed provider reasoning separately from the final 323 and retained it after reload/reopening. Retained evidence records IDs/counts/configuration, not reasoning bodies.
