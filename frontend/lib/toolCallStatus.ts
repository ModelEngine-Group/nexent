type ToolCallPart = {
  type?: string;
  status?: { type?: string };
  result?: unknown;
};

/**
 * Marks the tool calls emitted by the most recently completed ReAct code
 * block as complete. Tool calls in one code block are consecutive; a
 * non-tool part is the boundary to the preceding block.
 */
export function completeTrailingToolCalls(parts: ToolCallPart[]): void {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (part?.type !== "tool-call") break;

    if (part.status?.type === "incomplete") continue;
    part.status = { type: "complete" };
    // assistant-ui derives a tool call's status from the message while its
    // result is undefined. An empty result records successful completion
    // without inventing output for tools that did not emit any.
    if (part.result === undefined) part.result = "";
  }
}
