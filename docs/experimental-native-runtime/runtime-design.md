# Capability-aware native agent runtime on develop

This feature branch introduces the independent native runtime on develop (base 5876d6ec8). The standalone v2.8.4 experiment is not a merge source for main/develop. Implementation was migrated selectively; historical deployment evidence was not copied as acceptance evidence.

`NEXENT_AGENT_RUNTIME=codeagent` remains the default. `toolcalling` requests native execution. For every Agent, including lazily constructed children, `select_agent_runtime` examines the actual selected model's resolved profile: tools supported selects NativeToolCallingAgent; unsupported, unknown or absent evidence selects CoreAgent. Provider errors never trigger a silent downgrade. Requested/effective mode and fallback reason are traced on the Agent loop.

NativeServiceModel translates selected context and authorized tool schemas through the saved native converter into ModelRequest. The existing ModelService owns provider/role mapping, declared parameters, authentication, capacity, retry, concurrency, cancellation and telemetry. No parallel provider client or old reasoning catalog is used on this path. It preserves provider call/result IDs and supported text reasoning continuation using purpose=native_agent. The existing registered OpenAI adapter only allows that reasoning replay for declared supported reasoning; ordinary CodeAgent requests keep their previous replay policy.

Reasoning is independent of tool support and remains controlled by the resolved profile and operator settings. Unsupported reasoning does not cause a synthetic ReAct-thinking prompt; a tool-incompatible CodeAgent fallback replaces only the trusted platform execution-flow instruction with code-action guidance that requires no written thought. Authored task instructions remain intact. NL2Agent/NL2Skill keep their existing CodeAgent authoring protocols.

## Completion and interleaving

| Generation | Runtime policy |
|---|---|
| Nonempty content, no calls, finish_reason=stop | Final candidate; existing final verification policy applies |
| Content plus calls, finish_reason=tool_calls | Stream public content; execute authorized calls; return correlated results; continue |
| Calls only, finish_reason=tool_calls | Execute authorized calls and continue; standalone final_answer can terminate after verification |
| length/content_filter/refusal/missing/unknown/inconsistent terminal reason | No successful final answer and no tool effects from that generation |
| Cancellation or transport failure | Roll back uncommitted streamed text and release resources |

A standalone text-only normal stop is final under this policy, not a request for another generation. Mixed text/tool output supplies staged communication. Public text uses model_output SSE events independently of reasoning and the accepted final_answer event; no progress tool is introduced. Text control tags are not executable actions or observer parsing commands.

The frontend retains native text per step in arrival order around tools. Attempt rollback removes only failed text. An accepted content-only final step is promoted without duplication. Backend unit projection preserves earlier progress and promotes only the final step; saved-history rendering restores those positions. Existing CodeAgent final/reasoning slots remain supported.

Restricted code_execution, authorization/tool registry, local/Docker executor and Tool Bridge, planning/guardrail/verification callbacks and managed-child lifecycle reuse the established harness. Native tool execution remains sequential. Duplicate/missing complete call IDs fail; exactly empty ID fields on continuation fragments are treated as omissions, while changed/whitespace IDs remain invalid.
