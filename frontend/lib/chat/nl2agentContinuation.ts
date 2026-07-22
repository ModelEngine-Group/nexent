export const NL2AGENT_AUTO_CONTINUE_PREFIX = "[[NL2AGENT_AUTO_CONTINUE]]";
export const NL2AGENT_CARD_RETRY_PREFIX = "[[NL2AGENT_CARD_RETRY]]";

export const isNl2AgentAutoContinueText = (value: unknown): boolean =>
  [NL2AGENT_AUTO_CONTINUE_PREFIX, NL2AGENT_CARD_RETRY_PREFIX].some((prefix) =>
    String(value || "").startsWith(prefix)
  );

export const nl2AgentContinuationScopeKey = (
  conversationId?: number | null,
  draftAgentId?: number | null
): string => `${conversationId ?? "new"}:${draftAgentId ?? "none"}`;
