import { expect, test } from "vitest";

import {
  createConversationTitleRequest,
  type GenerateConversationTitleParams,
} from "@/lib/conversationTitle";

test("UT-FE-AUTO-19DA52E3B86508BF carries the send-instant model_id snapshot even after selectedModelId changes", () => {
  let selectedModelId: number | null = 7;
  const modelIdForRun = selectedModelId;

  selectedModelId = 9;

  const request = createConversationTitleRequest(42, "Question", modelIdForRun);

  expect(selectedModelId).toBe(9);
  expect(request).toEqual({
    conversation_id: 42,
    question: "Question",
    model_id: 7,
  });
});

test("passes conversation_id and question through untouched", () => {
  const request = createConversationTitleRequest(12345, "原始问题原文", 3);

  expect(request.conversation_id).toBe(12345);
  expect(request.question).toBe("原始问题原文");
  expect(request.model_id).toBe(3);
});

test("omits model_id for legacy default-model behavior when modelId is null", () => {
  const request = createConversationTitleRequest(42, "Question", null);

  expect(request).toEqual({
    conversation_id: 42,
    question: "Question",
  });
  expect("model_id" in request).toBe(false);
});

test("non-null model_id branch yields consistent repeated calls", () => {
  const first = createConversationTitleRequest(7, "repeat", 5);
  const second = createConversationTitleRequest(7, "repeat", 5);

  expect(first).toEqual(second);
});

test("null model_id branch yields consistent repeated calls", () => {
  const first = createConversationTitleRequest(1, "q", null);
  const second = createConversationTitleRequest(1, "q", null);

  expect(first).toEqual(second);
  expect("model_id" in first).toBe(false);
  expect("model_id" in second).toBe(false);
});
