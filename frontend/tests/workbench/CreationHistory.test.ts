import { expect, it } from "vitest";
import { restoreCreationHistory } from "@/features/workbench/creationHistory";
import type { ApiConversationDetail } from "@/types/conversation";

it("restores generated Skill files and completion from persisted turns", () => {
  const conversation = {
    message: [
      {
        role: "assistant",
        message: [
          {
            type: "agent_new_run",
            content: JSON.stringify({ type: "agent_new_run" }),
          },
          {
            type: "skill_body",
            content: JSON.stringify({
              type: "skill_body",
              content: "---\nname: demo\ndescription: Example\n---\nBody",
            }),
          },
          {
            type: "file_content",
            content: JSON.stringify({
              type: "file_content",
              path: "script.py",
              content: "print(1)",
            }),
          },
          {
            type: "done",
            content: JSON.stringify({ type: "done", content: "" }),
          },
        ],
      },
    ],
  } as ApiConversationDetail;
  const restored = restoreCreationHistory(conversation);
  expect(restored.skillDraft.complete).toBe(true);
  expect(restored.skillDraft.files["SKILL.md"]).toContain("name: demo");
  expect(restored.skillDraft.files["script.py"]).toBe("print(1)");
});

it("recognizes a completed Agent from its persisted state event", () => {
  const conversation = {
    message: [
      {
        role: "assistant",
        message: [
          {
            type: "nl2a_state",
            content: JSON.stringify({
              event: "agent_generation_completed",
              agent_id: 42,
            }),
          },
        ],
      },
    ],
  } as ApiConversationDetail;
  expect(restoreCreationHistory(conversation).agentCompleted).toBe(true);
});

it("rebuilds the creation draft from only the selected retry branch", () => {
  const conversation = {
    message: [
      { role: "assistant", message_id: 11, message_index: 1, message: [
        { type: "skill_body", content: JSON.stringify({ type: "skill_body", content: "old" }) },
      ] },
      { role: "assistant", message_id: 12, message_index: 1, message: [
        { type: "skill_body", content: JSON.stringify({ type: "skill_body", content: "new" }) },
      ] },
    ],
  } as ApiConversationDetail;
  expect(restoreCreationHistory(conversation).skillDraft.files["SKILL.md"]).toBe("new");
});
