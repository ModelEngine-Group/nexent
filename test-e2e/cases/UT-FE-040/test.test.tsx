import { describe, expect, it } from "vitest";
import {
  collectStream,
  restoreHistory,
  summaryEvent,
  summaryParts,
} from "../../infra/automation/d1/frontend/newchat-fixture";

describe("UT-FE-040 newchat history turn ownership", () => {
  it("UT-FE-040 groups normal chat output by the originating user turn", async () => {
    const history = await restoreHistory([
      { message_id: 1, role: "user", message: "first question" },
      {
        message_id: 2,
        role: "assistant",
        message: [
          {
            type: "tool",
            content: "",
            tool_name: "first-tool",
            tool_call_id: "tool-1",
            tool_arguments: {},
          },
          {
            type: "execution_logs",
            content: "first result",
            tool_call_id: "tool-1",
          },
        ],
      },
      { message_id: 3, role: "user", message: "follow-up question" },
      {
        message_id: 4,
        role: "assistant",
        message: [
          {
            type: "tool",
            content: "",
            tool_name: "second-tool",
            tool_call_id: "tool-2",
            tool_arguments: {},
          },
          {
            type: "execution_logs",
            content: "second result",
            tool_call_id: "tool-2",
          },
        ],
      },
    ]);
    expect(
      history.messages.map((entry) => [entry.message.id, entry.parentId]),
    ).toEqual([
      ["1", null],
      ["2", "1"],
      ["3", "2"],
      ["4", "3"],
    ]);
    const first = history.messages[1].message.content as any[];
    const second = history.messages[3].message.content as any[];
    expect(first).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "tool-call",
          tool_call_id: "tool-1",
          result: "first result",
        }),
      ]),
    );
    expect(second).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "tool-call",
          tool_call_id: "tool-2",
          result: "second result",
        }),
      ]),
    );
    expect(JSON.stringify(first)).not.toContain("second result");
    expect(JSON.stringify(second)).not.toContain("first result");
    expect(history.headId).toBe("4");
  });
});
