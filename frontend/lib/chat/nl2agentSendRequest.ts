import { isNl2AgentAutoContinueText } from "./nl2agentContinuation";

interface Nl2AgentSendRequest<TAttachment> {
  autoContinueText?: string;
  input: string;
  attachments: TAttachment[];
  activeConversationId?: number | null;
  activeDraftAgentId?: number | null;
  expectedConversationId?: number | null;
  expectedDraftAgentId?: number | null;
}

export interface ResolvedNl2AgentSendRequest<TAttachment> {
  isAutoContinue: boolean;
  outgoingText: string;
  outgoingAttachments: TAttachment[];
}

export const resolveNl2AgentSendRequest = <TAttachment>({
  autoContinueText,
  input,
  attachments,
  activeConversationId,
  activeDraftAgentId,
  expectedConversationId,
  expectedDraftAgentId,
}: Nl2AgentSendRequest<TAttachment>): ResolvedNl2AgentSendRequest<TAttachment> => {
  const isAutoContinue = isNl2AgentAutoContinueText(autoContinueText);
  if (
    isAutoContinue &&
    (activeConversationId !== expectedConversationId ||
      activeDraftAgentId !== expectedDraftAgentId)
  ) {
    throw new Error(
      "The active NL2AGENT conversation changed before automatic continuation."
    );
  }
  return {
    isAutoContinue,
    outgoingText: isAutoContinue ? autoContinueText!.trim() : input.trim(),
    outgoingAttachments: isAutoContinue ? [] : attachments,
  };
};
