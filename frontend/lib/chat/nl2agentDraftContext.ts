const asPositiveInteger = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
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

export const resolveNl2AgentRunnerId = (
  persistedRunnerId: unknown,
  selectedAgentId: unknown
): number | null =>
  asPositiveInteger(persistedRunnerId) ?? asPositiveInteger(selectedAgentId);
