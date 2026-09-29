interface ReasoningPart {
  type: "reasoning";
  text: string;
  status: { type: "running" | "done" };
}

/** Keep one reasoning block in its original position until a model/tool boundary. */
export function createReasoningAccumulator(parts: unknown[]) {
  let current: ReasoningPart | null = null;
  let pendingStepLabel = "";
  let pendingWhitespace = "";
  let currentHasStepLabel = false;
  let currentHasModelContent = false;
  const attempts = new Map<
    string,
    {
      hadCurrent: boolean;
      text: string;
      pendingStepLabel: string;
      pendingWhitespace: string;
      hadStepLabel: boolean;
      hadModelContent: boolean;
    }
  >();

  const replace = (next: ReasoningPart) => {
    const index = current ? parts.indexOf(current) : -1;
    if (index < 0) parts.push(next);
    else parts[index] = next;
    current = next;
  };

  return {
    queueStepLabel(label: string) {
      if (!label) return;
      // Older histories stored step_count after the model text. Attach that
      // late label to the open card instead of creating a second card.
      if (current && !currentHasStepLabel) {
        replace({ ...current, text: label + current.text });
        currentHasStepLabel = true;
        return;
      }
      if (current) this.close();
      replace({ type: "reasoning", text: label, status: { type: "running" } });
      currentHasStepLabel = true;
      currentHasModelContent = false;
      pendingStepLabel = "";
      pendingWhitespace = "";
    },
    append(text: string) {
      if (!text) return;
      if (!currentHasModelContent && !text.trim()) {
        pendingWhitespace += text;
        return;
      }
      replace({
        type: "reasoning",
        text: (current?.text ?? pendingStepLabel + pendingWhitespace) + text,
        status: { type: "running" },
      });
      pendingStepLabel = "";
      pendingWhitespace = "";
      currentHasModelContent = true;
    },
    close() {
      if (current) {
        if (currentHasStepLabel && !currentHasModelContent) {
          const index = parts.indexOf(current);
          if (index >= 0) parts.splice(index, 1);
        } else {
          replace({ ...current, status: { type: "done" } });
        }
        current = null;
      }
      pendingStepLabel = "";
      pendingWhitespace = "";
      currentHasStepLabel = false;
      currentHasModelContent = false;
    },
    beginAttempt(attemptId: string) {
      attempts.set(attemptId, {
        hadCurrent: current !== null,
        text: current?.text ?? "",
        pendingStepLabel,
        pendingWhitespace,
        hadStepLabel: currentHasStepLabel,
        hadModelContent: currentHasModelContent,
      });
    },
    rollbackAttempt(attemptId: string) {
      const checkpoint = attempts.get(attemptId);
      if (!checkpoint) return;
      attempts.delete(attemptId);
      pendingStepLabel = checkpoint.pendingStepLabel;
      pendingWhitespace = checkpoint.pendingWhitespace;
      currentHasStepLabel = checkpoint.hadStepLabel;
      currentHasModelContent = checkpoint.hadModelContent;
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
