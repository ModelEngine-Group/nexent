type ToolCallPart = {
  type?: string;
  status?: { type?: string };
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
  }
}
