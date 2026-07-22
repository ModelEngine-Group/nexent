import type { ChatMessageType } from "@/types/chat";
import type { AgentAutomationProposalData } from "@/types/agentAutomation";
import { agentAutomationService } from "@/services/agentAutomationService";

interface AutomationAnalysisRequest {
  conversationId?: number;
  agentId: number;
  message: string;
  modelId?: number | null;
}

export function canAnalyzeAutomationMessage(
  attachmentCount: number,
  agentId: number | null,
  message: string
): agentId is number {
  return attachmentCount === 0 && agentId !== null && Boolean(message);
}

export async function analyzeAutomationMessage({
  conversationId,
  agentId,
  message,
  modelId,
}: AutomationAnalysisRequest): Promise<AgentAutomationProposalData> {
  const timezone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  return agentAutomationService.createProposal({
    conversation_id: conversationId,
    agent_id: agentId,
    message,
    timezone,
    model_id: modelId,
  });
}

export async function getAutomationConversationIds(): Promise<Set<number>> {
  const conversationIds = new Set<number>();
  let page = 1;
  const pageSize = 100;
  while (true) {
    const result = await agentAutomationService.list({ page, pageSize });
    result.items.forEach((task) => conversationIds.add(task.conversation_id));
    if (page * pageSize >= result.total) break;
    page += 1;
  }
  return conversationIds;
}

export async function hydrateAutomationProposalMessages(
  messages: ChatMessageType[],
  conversationId: number
): Promise<ChatMessageType[]> {
  if (!messages.some((message) => message.automationProposal)) {
    return messages;
  }

  try {
    const task = await agentAutomationService.getByConversation(conversationId);
    if (!task?.agent_name) return messages;
    return messages.map((message) => {
      const proposal = message.automationProposal;
      if (!proposal?.task) return message;
      return {
        ...message,
        automationProposal: {
          ...proposal,
          task: {
            ...proposal.task,
            agent_name: task.agent_name,
          },
        },
      };
    });
  } catch {
    return messages;
  }
}

export async function hasAutomationForConversation(
  conversationId: number
): Promise<boolean> {
  return Boolean(
    await agentAutomationService.getByConversation(conversationId)
  );
}

export function createPreparingAutomationMessage(
  id: string,
  timestamp: Date
): ChatMessageType {
  return {
    id,
    role: "assistant",
    content: "",
    timestamp,
    isComplete: false,
    steps: [],
    automationProposal: { ui_state: "PREPARING" },
  };
}

export function resolveAutomationProposalMessage(
  messages: ChatMessageType[],
  messageId: string,
  proposal: AgentAutomationProposalData
): ChatMessageType[] {
  return messages.map((message) =>
    message.id === messageId
      ? {
          ...message,
          isComplete: true,
          automationProposal: proposal,
        }
      : message
  );
}

export function resolvePreparingMessageAsAgentReply(
  messages: ChatMessageType[],
  messageId: string,
  assistantMessage: ChatMessageType
): ChatMessageType[] {
  return messages.map((message) =>
    message.id === messageId ? assistantMessage : message
  );
}
