const asPositiveInteger = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
};

export const parseNl2AgentDraftMap = (
  value: string | null
): Record<string, number> => {
  if (!value) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed).flatMap(([conversationId, draftAgentId]) => {
        const normalizedConversationId = asPositiveInteger(conversationId);
        const normalizedDraftAgentId = asPositiveInteger(draftAgentId);
        return normalizedConversationId != null &&
          normalizedDraftAgentId != null
          ? [[String(normalizedConversationId), normalizedDraftAgentId]]
          : [];
      })
    );
  } catch {
    return {};
  }
};

export const resolveNl2AgentCardAgentId = (
  wrapperAgentId: unknown,
  itemAgentIds: unknown[],
  trustedDraftAgentId: unknown
): { agentId: number | null; mismatch: boolean } => {
  const payloadIds = [wrapperAgentId, ...itemAgentIds]
    .map(asPositiveInteger)
    .filter((agentId): agentId is number => agentId != null);
  const distinctPayloadIds = new Set(payloadIds);
  const trustedAgentId = asPositiveInteger(trustedDraftAgentId);
  const mismatch =
    distinctPayloadIds.size > 1 ||
    (trustedAgentId != null &&
      payloadIds.some((agentId) => agentId !== trustedAgentId));

  return {
    agentId: payloadIds[0] ?? trustedAgentId,
    mismatch,
  };
};

export const resolveNl2AgentDraftAgentId = (
  conversationId: number | null,
  draftByConversation: Record<string, number>,
  handoffConversationId: number | null,
  handoffDraftAgentId: number | null
): number | null => {
  if (conversationId == null) return null;

  const mappedDraftId = asPositiveInteger(
    draftByConversation[String(conversationId)]
  );
  if (mappedDraftId != null) return mappedDraftId;

  if (conversationId !== handoffConversationId) return null;
  return asPositiveInteger(handoffDraftAgentId);
};
