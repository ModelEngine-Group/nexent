interface ReasoningPart {
  type: "reasoning";
  text: string;
  status: { type: "running" | "done" };
}

/** Keep one reasoning block in its original position until a model/tool boundary. */
export function createReasoningAccumulator(parts: unknown[]) {
  let current: ReasoningPart | null = null;

  const replace = (next: ReasoningPart) => {
    const index = current ? parts.indexOf(current) : -1;
    if (index < 0) parts.push(next);
    else parts[index] = next;
    current = next;
  };

  return {
    append(text: string) {
      if (!text) return;
      replace({
        type: "reasoning",
        text: (current?.text ?? "") + text,
        status: { type: "running" },
      });
    },
    close() {
      if (!current) return;
      replace({ ...current, status: { type: "done" } });
      current = null;
    },
  };
}
