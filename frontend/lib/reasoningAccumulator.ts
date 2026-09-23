interface ReasoningPart {
  type: "reasoning";
  text: string;
  status: { type: "running" | "done" };
}

/** Keep one reasoning block in its original position until a model/tool boundary. */
export function createReasoningAccumulator(parts: unknown[]) {
  let current: ReasoningPart | null = null;
  const attempts = new Map<string, { hadCurrent: boolean; text: string }>();

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
    beginAttempt(attemptId: string) {
      attempts.set(attemptId, {
        hadCurrent: current !== null,
        text: current?.text ?? "",
      });
    },
    rollbackAttempt(attemptId: string) {
      const checkpoint = attempts.get(attemptId);
      if (!checkpoint) return;
      attempts.delete(attemptId);
      if (checkpoint.hadCurrent) {
        if (current) {
          const index = parts.indexOf(current);
          if (index < 0) return;
          const restored = {
            ...current,
            text: checkpoint.text,
          };
          parts[index] = restored;
          current = restored;
        }
      } else if (current) {
        const index = parts.indexOf(current);
        if (index >= 0) parts.splice(index, 1);
        current = null;
      }
    },
    commitAttempt(attemptId: string) {
      attempts.delete(attemptId);
    },
  };
}
