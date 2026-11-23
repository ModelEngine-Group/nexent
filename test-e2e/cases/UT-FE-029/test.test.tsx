import { describe, expect, it } from "vitest";
import {
  collectStream,
  restoreHistory,
  summaryEvent,
  summaryParts,
} from "../../infra/automation/d1/frontend/newchat-fixture";

describe("UT-FE-029 newchat SSE history summaries", () => {
  it("UT-FE-029 updates SSE history summaries idempotently", async () => {
    const results = await collectStream([
      summaryEvent({
        status: "accepted",
        covered_through_message_id: 4,
        summary: "older",
      }),
      summaryEvent({
        status: "accepted",
        covered_through_message_id: 4,
        summary: "newer",
      }),
    ]);
    expect(summaryParts(results[0])).toHaveLength(1);
    expect(summaryParts(results.at(-1))).toEqual([
      {
        type: "data",
        name: "history-summary",
        data: {
          status: "accepted",
          covered_through_message_id: 4,
          summary: "newer",
        },
      },
    ]);
    expect(JSON.stringify(results.at(-1))).not.toContain("older");
  });
});
