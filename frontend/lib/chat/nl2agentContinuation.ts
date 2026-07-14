export const NL2AGENT_AUTO_CONTINUE_PREFIX = "[[NL2AGENT_AUTO_CONTINUE]]";

export const isNl2AgentAutoContinueText = (value: unknown): boolean =>
  String(value || "").startsWith(NL2AGENT_AUTO_CONTINUE_PREFIX);

export const nl2AgentContinuationScopeKey = (
  conversationId?: number | null,
  draftAgentId?: number | null
): string => `${conversationId ?? "new"}:${draftAgentId ?? "none"}`;
