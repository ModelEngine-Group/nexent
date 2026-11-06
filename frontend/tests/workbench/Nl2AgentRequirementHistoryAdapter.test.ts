// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { findRequirementSubmission } from "@/app/newchat/ui/requirement-clarification-history";
import type { ApiConversationDetail, ApiMessage } from "@/types/conversation";
import type { Nl2aRequirementClarificationPayload } from "@/app/newchat/adapter/remote-chat-model-adapter";

const payload: Nl2aRequirementClarificationPayload = {
  subtype: "requirement_clarification",
  agent_id: 42,
  questions: [
    {
      question_id: "goal",
      question_type: "text",
      title: "Goal?",
      required: true,
      options: [],
      allow_other: false,
      other_input_expanded: false,
    },
  ],
};
const card = (id: number): ApiMessage => ({
  role: "assistant",
  message_id: id,
  status: "completed",
  message: [{ type: "nl2a", content: JSON.stringify(payload) }],
});
const action = (value = "Saved goal") => ({
  type: "nl2agent_card_action",
  subtype: "requirement_clarification",
  agent_id: 42,
  action: "submit",
  result: { answers: [{ question_id: "goal", value, other_text: null }] },
});
const response = (id: number, value: unknown): ApiMessage => ({
  role: "user",
  message_id: id,
  message: JSON.stringify(value),
});
async function restore(message: ApiMessage[]) {
  const saved = await new RemoteConversationHistoryAdapter(
    () => "91",
    async () => ({ remoteId: "91", externalId: "91" }),
    async () =>
      ({
        conversation_id: 91,
        create_time: 0,
        message,
      }) as ApiConversationDetail
  ).load();
  return saved.messages.map((item) => item.message);
}

it("restores from real persisted user-action metadata without changing the stored request", async () => {
  const messages = await restore([
    card(10),
    response(11, action()),
    card(12),
    response(13, action("Next goal")),
  ]);
  expect(messages[0].metadata?.custom?.nl2a).toMatchObject({
    content: payload,
  });
  expect(findRequirementSubmission(messages, "10", payload)).toEqual({
    messageId: "11",
    answers: [{ questionId: "goal", value: "Saved goal", otherText: null }],
  });
  expect(
    findRequirementSubmission(messages, "12", payload)?.answers[0].value
  ).toBe("Next goal");
  expect(messages[1].metadata?.custom?.nl2agentCardAction).toEqual(action());
});

it("does not borrow a later card's answers, skip ordinary user turns or cross conversation loads", async () => {
  const history = await restore([
    card(10),
    { role: "user", message_id: 11, message: "Unstructured legacy response" },
    card(12),
    response(13, action("Later")),
  ]);
  expect(findRequirementSubmission(history, "10", payload)).toBeUndefined();
  expect(
    findRequirementSubmission(history, "12", payload)?.answers[0].value
  ).toBe("Later");
  expect(
    findRequirementSubmission(history, "missing", payload)
  ).toBeUndefined();
  expect(
    findRequirementSubmission(await restore([card(10)]), "10", payload)
  ).toBeUndefined();
  expect(
    findRequirementSubmission(
      await restore([card(10), card(12), response(13, action())]),
      "10",
      payload
    )
  ).toBeUndefined();
});

it.each([
  { ...action(), result: { answers: [{ question_id: "goal", value: "   " }] } },
  { ...action(), agent_id: 43 },
  { ...action(), action: "cancel" },
  { ...action(), subtype: "installed_resource_binding" },
  { ...action(), result: { answers: [] } },
  { ...action(), result: { answers: [null] } },
  {
    ...action(),
    result: { answers: [{ question_id: "unknown", value: "Wrong" }] },
  },
  {
    ...action(),
    result: { answers: [{ question_id: "goal", value: ["Wrong type"] }] },
  },
  {
    ...action(),
    result: {
      answers: [{ question_id: "goal", value: "Goal", other_text: 7 }],
    },
  },
  {
    ...action(),
    result: {
      answers: [
        { question_id: "goal", value: "Goal", other_text: "Not allowed" },
      ],
    },
  },
])(
  "ignores malformed or mismatched submission %# without inferring completion",
  async (value) => {
    expect(
      findRequirementSubmission(
        await restore([card(10), response(11, value)]),
        "10",
        payload
      )
    ).toBeUndefined();
  }
);

it("validates choices and preserves other-only answers without confusing repeated question IDs", () => {
  const choices: Nl2aRequirementClarificationPayload = {
    ...payload,
    questions: [
      {
        ...payload.questions[0],
        question_type: "multiple_choice",
        options: [{ option_id: "a", label: "A" }],
        allow_other: true,
        other_input_expanded: true,
      },
    ],
  };
  const messages = (value: unknown, other_text: unknown = null) => [
    { id: "10", role: "assistant" },
    {
      id: "11",
      role: "user",
      metadata: {
        custom: {
          nl2agentCardAction: {
            ...action(),
            result: { answers: [{ question_id: "goal", value, other_text }] },
          },
        },
      },
    },
  ];
  expect(
    findRequirementSubmission(messages(["a"], "Other"), "10", choices)
      ?.answers[0]
  ).toEqual({ questionId: "goal", value: ["a"], otherText: "Other" });
  expect(
    findRequirementSubmission(messages([], "Other only"), "10", choices)
      ?.answers[0].value
  ).toEqual([]);
  for (const value of [["unknown"], [1], "a", []])
    expect(
      findRequirementSubmission(messages(value), "10", choices)
    ).toBeUndefined();
});
