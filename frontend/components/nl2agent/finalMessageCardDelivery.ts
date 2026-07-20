export interface Nl2AgentCardPresentationInput {
  isComplete: boolean;
  isStreaming: boolean;
  hasMessageId: boolean;
  hasValidationFailure: boolean;
  isLatestMessage: boolean;
  readOnly: boolean;
}

export const resolveNl2AgentCardPresentation = ({
  isComplete,
  isStreaming,
  hasMessageId,
  hasValidationFailure,
  isLatestMessage,
  readOnly,
}: Nl2AgentCardPresentationInput): {
  renderMode: "placeholder" | "readonly" | "interactive";
  registrationEnabled: boolean;
} => {
  const displayReady = isComplete && !hasValidationFailure;
  const deliveryReady = displayReady && hasMessageId && !isStreaming;
  return {
    renderMode: !displayReady
      ? "placeholder"
      : !isLatestMessage
        ? "readonly"
        : "interactive",
    registrationEnabled: deliveryReady && !readOnly && isLatestMessage,
  };
};
