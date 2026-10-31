import { describe, expect, it } from "vitest";
import {
  collectStream,
  restoreHistory,
  summaryEvent,
  summaryParts,
} from "../../infra/automation/d1/frontend/newchat-fixture";

describe("UT-FE-003 newchat tool and completion state", () => {
  it("UT-FE-003 transforms chat messages without losing tool and completion state", async () => {
    const events = [
      {
        type: "tool",
        content: "",
        tool_name: "lookup",
        tool_call_id: "tool-1",
        tool_arguments: {},
      },
      { type: "execution_logs", content: "done", tool_call_id: "tool-1" },
      { type: "final_answer", content: "finished" },
      { type: "done", content: "" },
    ];
    const results = await collectStream(events);
    const streamed = results.at(-1).content;
    const history = await restoreHistory([
      { message_id: 1, role: "user", message: "run" },
      { message_id: 2, role: "assistant", message: events },
    ]);
    const restored = history.messages[1].message;
    for (const content of [streamed, restored.content]) {
      expect(content).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            type: "tool-call",
            tool_call_id: "tool-1",
            toolName: "lookup",
            result: "done",
          }),
          expect.objectContaining({ type: "text", text: "finished" }),
        ]),
      );
      expect(
        content.filter((part: any) => part.type === "tool-call"),
      ).toHaveLength(1);
    }
    expect(restored.status).toMatchObject({ type: "complete" });
  });
});
