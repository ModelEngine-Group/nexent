import type { ChatMessageType } from "@/types/chat";
import type { AgentAutomationProposalData } from "@/types/agentAutomation";
import { agentAutomationService } from "@/services/agentAutomationService";
import {
  isTurnResourceType,
  parseTurnResourceInvocation,
} from "@/features/turnResourceInvocation/parser";

interface AutomationAnalysisRequest {
  conversationId?: number;
  agentId: number;
  message: string;
  modelId?: number | null;
}

export function canHandleAutomationInvocation(
  attachmentCount: number,
  agentId: number | null,
  message: string
): agentId is number {
  const invocation = parseTurnResourceInvocation(message);
  return (
    attachmentCount === 0 &&
    agentId !== null &&
    isTurnResourceType(invocation, "automation") &&
    Boolean(invocation.argument)
  );
}

export async function createAutomationProposalFromInvocation({
  conversationId,
  agentId,
  message,
  modelId,
}: AutomationAnalysisRequest): Promise<AgentAutomationProposalData> {
  const invocation = parseTurnResourceInvocation(message);
  if (!isTurnResourceType(invocation, "automation")) {
    throw new Error("Message is not an automation resource invocation");
  }
  const timezone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  return agentAutomationService.createProposal({
    conversation_id: conversationId,
    agent_id: agentId,
    message: invocation.sourceMessage,
    instruction: invocation.argument,
    timezone,
    model_id: modelId,
  });
}

export async function getAutomationConversationIds(): Promise<Set<number>> {
  const tasks = await agentAutomationService.list();
  return new Set(tasks.map((task) => task.conversation_id));
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
