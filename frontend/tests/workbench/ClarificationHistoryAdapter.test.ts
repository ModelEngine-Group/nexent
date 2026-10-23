// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import type { ApiConversationDetail, ApiMessage } from "@/types/conversation";

const form = {
  schema_version: 1,
  questions: [{ id: "same", type: "text", title: "Goal?" }],
};
const card = (id: number): ApiMessage => ({
  role: "assistant",
  message_id: id,
  status: "completed",
  message: [
    { type: "human_interaction", unit_index: 7, content: JSON.stringify(form) },
  ],
});
const response = {
  schema_version: 1,
  source_message_id: 10,
  unit_index: 7,
  form,
  answers: [{ questionId: "same", value: "Saved goal", otherText: null }],
};
async function restore(message: ApiMessage[]) {
  const detail = {
    conversation_id: "42",
    create_time: 0,
    message,
  } as ApiConversationDetail;
  return new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  ).load();
}

it("associates responses by original message/unit identity despite repeated question IDs", async () => {
  const history = await restore([
    card(10),
    {
      role: "user",
      message_id: 11,
      message: "Readable answer",
      clarification_response: response,
    },
    card(12),
  ]);
  const first = history.messages[0].message.content.find(
    (part) => part.type === "data"
  );
  expect(first).toMatchObject({
    name: "clarification",
    data: { submitted: true, answers: response.answers },
  });
  expect(history.messages[1].message.content).toEqual([
    { type: "text", text: "Readable answer" },
  ]);
  const later = history.messages[2].message.content.find(
    (part) => part.type === "data"
  );
  expect(later).toMatchObject({ name: "clarification" });
  expect(later).not.toHaveProperty("data.submitted");
});

it("does not share answers across history loads or infer submission for legacy cards", async () => {
  const history = await restore([card(10)]);
  expect(history.messages[0].message.content[0]).not.toHaveProperty(
    "data.submitted"
  );
  const malformed = await restore([
    card(10),
    {
      role: "user",
      message: "legacy answer",
      clarification_response: { ...response, unit_index: 8 },
    },
  ]);
  expect(malformed.messages[0].message.content[0]).not.toHaveProperty(
    "data.submitted"
  );
});
