import { describe, expect, it } from "vitest";
import { createFinalAnswerProjection } from "../../../frontend/lib/finalAnswerProjection";
import { createReasoningAccumulator } from "../../../frontend/lib/reasoningAccumulator";

describe("FAF-D1-002 answer projection", () => {
  it("keeps pure answer steps invisible and merges streamed completion", () => {
    const parts: any[] = [];
    const thoughts = createReasoningAccumulator(parts);
    thoughts.queueStepLabel("Step 1");
    expect(parts).toEqual([]);
    const answers = createFinalAnswerProjection(parts);
    answers.apply({
      type: "final_answer",
      content: "Hello ",
      answer_phase: "delta",
    });
    answers.apply({
      type: "final_answer",
      content: "world",
      answer_phase: "delta",
    });
    thoughts.close();
    answers.apply({
      type: "final_answer",
      content: "",
      answer_phase: "complete",
    });
    expect(parts).toEqual([
      { type: "text", text: "Hello world", isFinalAnswer: true },
    ]);
  });
  it("preserves mixed reasoning and isolates sibling answers", () => {
    const parts: any[] = [];
    const thoughts = createReasoningAccumulator(parts);
    thoughts.queueStepLabel("Step 1 ");
    thoughts.append("Reason.");
    thoughts.close();
    const answers = createFinalAnswerProjection(parts);
    answers.apply({
      type: "final_answer",
      content: "Parent",
      answer_phase: "delta",
    });
    answers.apply(
      {
        type: "final_answer",
        content: "Child",
        invocation_id: "child",
        answer_phase: "delta",
      },
      { subagentId: 2 },
    );
    answers.apply({
      type: "final_answer",
      content: "",
      invocation_id: "child",
      answer_phase: "complete",
    });
    expect(parts.map((part) => part.text)).toEqual([
      "Step 1 Reason.",
      "Parent",
      "Child",
    ]);
    expect(parts[2].metadata).toEqual({ subagentId: 2 });
  });
  it("explicitly reclassifies legacy output while preserving deep reasoning", () => {
    const parts: any[] = [];
    const thoughts = createReasoningAccumulator(parts);
    const answers = createFinalAnswerProjection(parts);
    const event = { type: "step_count", content: "Step 1 ", step_id: "one" };
    thoughts.queueStepLabel(event.content);
    answers.recordStep(event);
    thoughts.append("Deep. ");
    answers.recordReasoning(
      { ...event, type: "model_output_deep_thinking", content: "Deep. " },
      parts[0],
    );
    thoughts.append("Answer");
    answers.recordReasoning(
      { ...event, type: "model_output_thinking", content: "Answer" },
      parts[0],
    );
    thoughts.detach();
    answers.apply({
      ...event,
      type: "final_answer",
      content: "",
      reclassify_step: true,
    });
    thoughts.close();
    expect(parts.map((part) => part.text)).toEqual(["Step 1 Deep. ", "Answer"]);
  });
  it("rolls back answer fragments and accepts a corrected completion", () => {
    const parts: any[] = [];
    const answers = createFinalAnswerProjection(parts);
    answers.control({
      type: "model_attempt_control",
      content: "",
      phase: "begin",
      attempt_id: "a",
    });
    answers.apply({
      type: "final_answer",
      content: "Wrong",
      answer_phase: "delta",
    });
    answers.control({
      type: "model_attempt_control",
      content: "",
      phase: "rollback",
      attempt_id: "a",
    });
    expect(parts).toEqual([]);
    answers.apply({
      type: "final_answer",
      content: "Candidate",
      answer_phase: "delta",
    });
    answers.apply({
      type: "final_answer",
      content: "Accepted",
      answer_phase: "complete",
    });
    expect(parts.map((part) => part.text)).toEqual(["Accepted"]);
  });
});
