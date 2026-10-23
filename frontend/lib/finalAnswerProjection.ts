interface AnswerEvent {
  type: string;
  content: string;
  invocation_id?: string;
  step_id?: string;
  attempt_id?: string;
  phase?: string;
  answer_phase?: "delta" | "complete";
  reclassify_step?: boolean;
}

/** Project one answer slot per invocation, using roles rather than text matching. */
export function createFinalAnswerProjection(
  parts: any[],
  remove: (index: number) => void = (index) => {
    parts.splice(index, 1);
  }
) {
  const answers = new Map<string, any>();
  const labels = new Map<string, string>();
  const reasoning = new Map<
    string,
    { part: any; deep: string; body: string }
  >();
  const attempts = new Map<
    string,
    {
      scope: string;
      part?: any;
      text: string;
      stepId?: string;
      reasoning: [string, { part: any; deep: string; body: string }][];
    }
  >();
  const scope = (event: AnswerEvent) => event.invocation_id ?? "parent";
  const step = (event: AnswerEvent) => `${scope(event)}/${event.step_id ?? ""}`;
  return {
    recordStep(event: AnswerEvent) {
      labels.set(step(event), event.content);
    },
    recordReasoning(event: AnswerEvent, part: any) {
      if (!part) return;
      const key = step(event);
      const entry = reasoning.get(key) ?? { part, deep: "", body: "" };
      entry.part = part;
      if (event.type === "model_output_deep_thinking")
        entry.deep += event.content;
      else entry.body += event.content;
      reasoning.set(key, entry);
    },
    control(event: AnswerEvent) {
      if (!event.attempt_id) return;
      const key = scope(event);
      if (event.phase === "begin") {
        const part = answers.get(key);
        attempts.set(event.attempt_id, {
          scope: key,
          part,
          text: part?.text ?? "",
          stepId: part?.answerStepId,
          reasoning: [...reasoning]
            .filter(([id]) => id.startsWith(key + "/"))
            .map(([id, entry]) => [id, { ...entry }]),
        });
      } else {
        const checkpoint = attempts.get(event.attempt_id);
        attempts.delete(event.attempt_id);
        if (event.phase !== "rollback" || !checkpoint) return;
        for (const id of reasoning.keys()) {
          if (id.startsWith(checkpoint.scope + "/")) reasoning.delete(id);
        }
        for (const [id, entry] of checkpoint.reasoning)
          reasoning.set(id, entry);
        const part = answers.get(checkpoint.scope);
        if (part && part !== checkpoint.part) {
          const index = parts.indexOf(part);
          if (index >= 0) remove(index);
        }
        if (checkpoint.part) {
          checkpoint.part.text = checkpoint.text;
          checkpoint.part.answerStepId = checkpoint.stepId;
          answers.set(checkpoint.scope, checkpoint.part);
        } else answers.delete(checkpoint.scope);
      }
    },
    apply(event: AnswerEvent, metadata?: object) {
      let content = event.content;
      if (event.reclassify_step && event.step_id) {
        for (const [key, entry] of reasoning) {
          if (key !== step(event)) continue;
          const part = entry.part;
          if (!content) content = entry.body;
          if (entry.deep.trim()) {
            part.text = (labels.get(key) ?? "") + entry.deep;
            part.status = { type: "done" };
          } else {
            const index = parts.indexOf(part);
            if (index >= 0) remove(index);
          }
          reasoning.delete(key);
        }
      }
      const key = scope(event);
      let part = answers.get(key);
      if (!part && content) {
        part = {
          type: "text",
          text: "",
          isFinalAnswer: true,
          ...(metadata && { metadata }),
        };
        parts.push(part);
        answers.set(key, part);
      }
      if (!part) return;
      if (event.answer_phase === "delta") {
        if (event.step_id && part.answerStepId !== event.step_id)
          part.text = "";
        if (event.step_id) part.answerStepId = event.step_id;
        part.text += content;
      } else if (content) part.text = content;
    },
  };
}
