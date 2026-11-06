// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Nl2AgentFlowProvider } from "@/contexts/nl2AgentFlow";
import { RequirementClarificationCard } from "@/app/newchat/ui/requirement-clarification-card";
import type { Nl2aRequirementClarificationPayload } from "@/app/newchat/adapter/remote-chat-model-adapter";

const append = vi.hoisted(() => vi.fn());
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      append,
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
}));
beforeEach(() => append.mockClear());

const payload: Nl2aRequirementClarificationPayload = {
  subtype: "requirement_clarification",
  agent_id: 42,
  questions: [
    {
      question_id: "audience",
      question_type: "single_choice",
      title: "Audience?",
      required: true,
      options: [
        { option_id: "team", label: "Internal team" },
        { option_id: "personal", label: "Personal" },
      ],
      allow_other: false,
      other_input_expanded: false,
    },
    {
      question_id: "scope",
      question_type: "multiple_choice",
      title: "Scope?",
      required: true,
      options: [
        { option_id: "text", label: "Text" },
        { option_id: "files", label: "Files" },
      ],
      allow_other: true,
      other_input_expanded: true,
    },
    {
      question_id: "constraints",
      question_type: "text",
      title: "Constraints?",
      required: false,
      options: [],
      allow_other: false,
      other_input_expanded: false,
    },
  ],
};
const answers = [
  { questionId: "audience", value: "team", otherText: null },
  {
    questionId: "scope",
    value: ["text", "files"],
    otherText: "Pasted text only",
  },
  {
    questionId: "constraints",
    value: "No network or scheduled tasks",
    otherText: null,
  },
];
const view = (
  sourceMessageId = "10",
  submission?: { messageId: string; answers: typeof answers }
) => (
  <Nl2AgentFlowProvider>
    <RequirementClarificationCard
      payload={payload}
      disabled
      sourceMessageId={sourceMessageId}
      submission={submission}
    />
  </Nl2AgentFlowProvider>
);

it("restores saved choices, other text and submitted state without replaying a run", () => {
  render(view("10", { messageId: "11", answers }));
  expect(screen.getByRole("radio", { name: "Internal team" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Text" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Files" })).toBeChecked();
  expect(screen.getByRole("textbox", { name: "Other" })).toHaveValue(
    "Pasted text only"
  );
  expect(screen.getByRole("textbox", { name: "Constraints?" })).toHaveValue(
    "No network or scheduled tasks"
  );
  const submit = screen.getByRole("button", { name: "Submitted" });
  expect(submit).toBeDisabled();
  expect(screen.getByRole("radio", { name: "Internal team" })).toBeDisabled();
  fireEvent.click(submit);
  expect(append).not.toHaveBeenCalled();
});

it("hydrates answers arriving after mount and resets when switching to another card", () => {
  const { rerender } = render(view());
  expect(screen.getByRole("textbox", { name: "Constraints?" })).toHaveValue("");
  rerender(view("10", { messageId: "11", answers }));
  expect(screen.getByRole("radio", { name: "Internal team" })).toBeChecked();
  expect(screen.getByRole("textbox", { name: "Constraints?" })).toHaveValue(
    "No network or scheduled tasks"
  );
  rerender(view("12"));
  expect(
    screen.getByRole("radio", { name: "Internal team" })
  ).not.toBeChecked();
  expect(screen.getByRole("textbox", { name: "Constraints?" })).toHaveValue("");
  expect(screen.queryByRole("button", { name: "Submitted" })).toBeNull();
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
});

it("locks a persisted submission even when the caller does not mark the card disabled", () => {
  render(
    <Nl2AgentFlowProvider>
      <RequirementClarificationCard
        payload={payload}
        sourceMessageId="10"
        submission={{ messageId: "11", answers }}
      />
    </Nl2AgentFlowProvider>
  );
  expect(screen.getByRole("button", { name: "Submitted" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "Constraints?" })).toBeDisabled();
  expect(screen.getByRole("radio", { name: "Internal team" })).toBeChecked();
});

it("keeps unanswered historical cards locked without inventing submitted answers", () => {
  render(view());
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  expect(
    screen.getByRole("radio", { name: "Internal team" })
  ).not.toBeChecked();
  expect(screen.getByRole("textbox", { name: "Constraints?" })).toHaveValue("");
});

it("preserves an unsent active answer across unrelated rerenders", () => {
  const active = () => (
    <Nl2AgentFlowProvider>
      <RequirementClarificationCard
        sourceMessageId="active"
        payload={{ ...payload }}
      />
    </Nl2AgentFlowProvider>
  );
  const { rerender } = render(active());
  fireEvent.change(screen.getByRole("textbox", { name: "Constraints?" }), {
    target: { value: "Unsent requirement draft" },
  });
  rerender(active());
  expect(screen.getByRole("textbox", { name: "Constraints?" })).toHaveValue(
    "Unsent requirement draft"
  );
});

it("validates required answers and submits a live card only once", async () => {
  render(
    <Nl2AgentFlowProvider>
      <RequirementClarificationCard
        payload={payload}
        sourceMessageId="active"
      />
    </Nl2AgentFlowProvider>
  );
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  fireEvent.click(screen.getByRole("radio", { name: "Internal team" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Text" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Constraints?" }), {
    target: { value: "Keep my constraints" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Submitted" })).toBeDisabled()
  );
  fireEvent.click(screen.getByRole("button", { name: "Submitted" }));
  expect(append).toHaveBeenCalledTimes(1);
  expect(append).toHaveBeenCalledWith(
    expect.objectContaining({
      startRun: true,
      metadata: {
        custom: {
          nl2agentCardAction: expect.objectContaining({
            result: {
              answers: [
                { question_id: "audience", value: "team", other_text: null },
                { question_id: "scope", value: ["text"], other_text: null },
                {
                  question_id: "constraints",
                  value: "Keep my constraints",
                  other_text: null,
                },
              ],
            },
          }),
        },
      },
    })
  );
});
