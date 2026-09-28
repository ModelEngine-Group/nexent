import type { ApiConversationDetail } from "@/types/conversation";
import {
  applySkillCreationEvent,
  initialSkillCreationDraft,
  type SkillCreationDraft,
  type SkillCreationEvent,
} from "./creationRuntime";

/** Rebuild creation UI state from persisted SSE units after opening a session. */
export function restoreCreationHistory(conversation: ApiConversationDetail): {
  skillDraft: SkillCreationDraft;
  agentCompleted: boolean;
} {
  let skillDraft = initialSkillCreationDraft;
  let agentCompleted = false;
  const messages = conversation.message ?? [];
  const selectedVariantByIndex = new Map<number, number>();
  for (const [position, item] of messages.entries()) {
    if (item.role === "assistant" && typeof item.message_index === "number") {
      selectedVariantByIndex.set(item.message_index, position);
    }
  }
  for (const [position, message] of messages.entries()) {
    if (
      typeof message.message_index === "number" &&
      message.role === "assistant" &&
      selectedVariantByIndex.get(message.message_index) !== position
    ) continue;
    if (message.role !== "assistant" || !Array.isArray(message.message))
      continue;
    for (const part of message.message) {
      if (part.type === "nl2a_state") {
        try {
          const state = JSON.parse(part.content) as { event?: string };
          if (state.event === "agent_generation_completed")
            agentCompleted = true;
        } catch {
          // Ignore malformed historical metadata.
        }
      }
      if (part.type === "skill_body" || part.type === "file_content") {
        try {
          const event = JSON.parse(part.content) as SkillCreationEvent;
          skillDraft = applySkillCreationEvent(skillDraft, event);
        } catch {
          // Ignore malformed file units while retaining other files.
        }
      } else if (
        [
          "agent_new_run",
          "target_files",
          "model_attempt_control",
          "done",
          "error",
        ].includes(part.type)
      ) {
        let attributes: Partial<SkillCreationEvent> = {};
        try {
          attributes = JSON.parse(part.content) as Partial<SkillCreationEvent>;
        } catch {
          // Most non-file units contain plain text.
        }
        skillDraft = applySkillCreationEvent(skillDraft, {
          ...attributes,
          type: part.type,
        });
      }
    }
  }
  return { skillDraft, agentCompleted };
}
