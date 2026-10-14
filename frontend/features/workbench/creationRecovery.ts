/** Recovery is allowed only after restoration could not load the bound draft. */
export function shouldAutoCreateAgentDraft(
  conversationId: string | undefined,
  recoverable: boolean
): boolean {
  const numericId = Number(conversationId);
  return !Number.isInteger(numericId) || numericId <= 0 || recoverable;
}

export function isAgentCreationAwaitingDraft(
  remoteId: string | undefined,
  hasCreationAgent: boolean,
  recoverable: boolean
): boolean {
  const numericId = Number(remoteId);
  return (
    Number.isInteger(numericId) &&
    numericId > 0 &&
    !hasCreationAgent &&
    !recoverable
  );
}
