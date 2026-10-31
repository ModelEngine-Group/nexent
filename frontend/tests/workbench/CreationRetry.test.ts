import { expect, it } from "vitest";
import { getCreationRetryTarget } from "@/features/workbench/creationRetry";

it("targets a persisted creation user turn by id and logical index", () => {
  expect(getCreationRetryTarget([
    { id: "100", role: "user", metadata: { custom: { historicalMessageIndex: 4 } } },
    { id: "101", role: "assistant" },
  ], "100")).toEqual({ retry_user_message_id: 100, retry_message_index: 4 });
});

it("targets a freshly sent creation user turn by its path position", () => {
  expect(getCreationRetryTarget([
    { id: "first", role: "user" },
    { id: "answer", role: "assistant" },
    { id: "second", role: "user" },
  ], "second")).toEqual({ retry_message_index: 2 });
});
