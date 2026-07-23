import { describe, expect, it } from "vitest";

import type { ApiMessage } from "@/types/conversation";
import {
  buildBranchableHistory,
  collapseRefreshUserMessages,
} from "../conversation-thread-list-adapter";

const actionMessage = (messageId: number, actionId: string): ApiMessage => ({
  message_id: messageId,
  role: "user",
  message: "Confirmed requirements: build a support agent",
  message_type: "nl2agent_action",
  message_metadata: {
    action_id: actionId,
    action: "confirm_requirements",
    workflow_revision: 19,
  },
});

describe("NL2AGENT action context history", () => {
  it("preserves distinct structured actions and ordinary user messages", () => {
    const messages: ApiMessage[] = [
      actionMessage(1, "action-1"),
      { message_id: 2, role: "assistant", message: [] },
      {
        message_id: 3,
        role: "user",
        message: "Please make the agent more concise",
      },
      { message_id: 4, role: "assistant", message: [] },
      actionMessage(5, "action-2"),
    ];

    expect(
      collapseRefreshUserMessages(messages).map((item) => item.message_id)
    ).toEqual([1, 2, 3, 4, 5]);
  });

  it("deduplicates only repeated persistence of the same action id", () => {
    const messages: ApiMessage[] = [
      actionMessage(1, "action-1"),
      { message_id: 2, role: "assistant", message: [] },
      actionMessage(3, "action-1"),
      actionMessage(4, "action-2"),
    ];

    expect(
      collapseRefreshUserMessages(messages).map((item) => item.message_id)
    ).toEqual([1, 2, 4]);
  });

  it("uses a user action as the parent of the following assistant output", () => {
    const messages = buildBranchableHistory([
      { id: "assistant-1", role: "assistant", content: [] },
      { id: "action-1", role: "user", content: [] },
      { id: "assistant-2", role: "assistant", content: [] },
    ]);

    expect(
      messages.map(({ message, parentId }) => [message.id, parentId])
    ).toEqual([
      ["assistant-1", null],
      ["action-1", "assistant-1"],
      ["assistant-2", "action-1"],
    ]);
  });
});
