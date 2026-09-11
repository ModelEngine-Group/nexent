export type AgentShareChatRole = "user" | "assistant";

export interface AgentShareChatMessage {
  id: string;
  role: AgentShareChatRole;
  content: string;
}

interface AgentShareHistoryMessage {
  role?: unknown;
  message?: unknown;
  message_id?: unknown;
}

interface AgentShareHistoryConversation {
  message?: unknown;
}

export interface AgentShareStreamEvent {
  type?: unknown;
  content?: unknown;
}

export function extractAgentShareHistory(
  history: unknown
): AgentShareChatMessage[] {
  const conversation = Array.isArray(history)
    ? (history[0] as AgentShareHistoryConversation | undefined)
    : undefined;
  if (!Array.isArray(conversation?.message)) return [];

  return conversation.message.flatMap<AgentShareChatMessage>((item, index) => {
    const message = item as AgentShareHistoryMessage;
    if (message.role === "user" && typeof message.message === "string") {
      return [
        {
          id: `history-user-${message.message_id ?? index}`,
          role: "user" as const,
          content: message.message,
        },
      ];
    }

    if (message.role !== "assistant" || !Array.isArray(message.message)) {
      return [];
    }
    const finalAnswer = message.message.find(
      (unit): unit is { type?: unknown; content?: unknown } =>
        typeof unit === "object" &&
        unit !== null &&
        unit.type === "final_answer"
    );
    if (typeof finalAnswer?.content !== "string") return [];

    return [
      {
        id: `history-assistant-${message.message_id ?? index}`,
        role: "assistant" as const,
        content: finalAnswer.content,
      },
    ];
  });
}

export function parseAgentShareSseLine(
  line: string
): AgentShareStreamEvent | null {
  if (!line.startsWith("data:")) return null;
  try {
    const event = JSON.parse(line.slice(5).trim()) as AgentShareStreamEvent;
    return event && typeof event === "object" ? event : null;
  } catch {
    return null;
  }
}

export function getAgentShareFinalAnswerChunk(
  event: AgentShareStreamEvent
): string | null {
  return event.type === "final_answer" && typeof event.content === "string"
    ? event.content
    : null;
}

export function getAgentShareStreamError(
  event: AgentShareStreamEvent
): string | null {
  return event.type === "error" && typeof event.content === "string"
    ? event.content
    : null;
}
