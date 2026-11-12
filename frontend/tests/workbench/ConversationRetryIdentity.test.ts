// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import {
  acknowledgeConversationUser,
  getConversationRetryTarget,
} from "@/lib/conversationRetry";

it("uses an acknowledged live user without inferring identity from equal text or position", () => {
  const users = [
    { id: "local-first", role: "user" },
    { id: "local-second", role: "user" },
  ];
  expect(getConversationRetryTarget(users, "local-first")).toBeNull();
  acknowledgeConversationUser("local-first", 501, 0);
  acknowledgeConversationUser("local-second", 503, 2);
  expect(getConversationRetryTarget(users, "local-first")).toEqual({
    retry_user_message_id: 501,
    retry_message_index: 0,
  });
  expect(getConversationRetryTarget(users, "local-second")).toEqual({
    retry_user_message_id: 503,
    retry_message_index: 2,
  });
});

it("uses the persisted ID and logical index after reload", () => {
  expect(
    getConversationRetryTarget(
      [
        {
          id: "99",
          role: "user",
          metadata: { custom: { historicalMessageIndex: 12 } },
        },
      ],
      "99"
    )
  ).toEqual({ retry_user_message_id: 99, retry_message_index: 12 });
});

it("rejects missing parents, assistant parents and invalid acknowledgements", () => {
  acknowledgeConversationUser("invalid", 0, -1);
  expect(
    getConversationRetryTarget([{ id: "invalid", role: "user" }], "invalid")
  ).toBeNull();
  expect(
    getConversationRetryTarget([{ id: "99", role: "assistant" }], "99")
  ).toBeNull();
  expect(getConversationRetryTarget([], "missing")).toBeNull();
});
