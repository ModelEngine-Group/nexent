// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ClarificationCard } from "@/components/interaction/clarification-card";
import {
  appendClarificationPart,
  parseClarificationResponse,
  toCardQuestions,
} from "@/lib/clarification";

const form = {
  schema_version: 1 as const,
  questions: [
    {
      id: "text",
      type: "text" as const,
      title: "Goal?",
      required: true,
      options: [],
      allow_other: false,
      placeholder: "",
    },
    {
      id: "single",
      type: "single_choice" as const,
      title: "Period?",
      required: true,
      options: [
        { id: "a", label: "A" },
        { id: "b", label: "B" },
      ],
      allow_other: false,
      placeholder: "",
    },
    {
      id: "multi",
      type: "multiple_choice" as const,
      title: "Metrics?",
      required: true,
      options: [
        { id: "a", label: "First" },
        { id: "b", label: "Second" },
      ],
      allow_other: true,
      placeholder: "",
    },
  ],
};
const answers = [
  { questionId: "text", value: "Saved goal", otherText: null },
  { questionId: "single", value: "b", otherText: null },
  { questionId: "multi", value: ["a", "b"], otherText: "Other metric" },
];
const props = {
  title: "Clarification",
  description: "Details",
  questions: toCardQuestions(form.questions),
  submitLabel: "Submit",
  submittedLabel: "Submitted",
  otherLabel: "Other",
  onSubmit: vi.fn(),
};

it("restores all saved controls and submitted state after remount", () => {
  const first = render(
    <ClarificationCard {...props} initialAnswers={answers} submitted />
  );
  expect(screen.getByRole("textbox", { name: "Goal?" })).toHaveValue(
    "Saved goal"
  );
  expect(screen.getByRole("radio", { name: "B" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "First" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Second" })).toBeChecked();
  expect(screen.getByRole("textbox", { name: "Other" })).toHaveValue(
    "Other metric"
  );
  expect(screen.getByRole("button", { name: "Submitted" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "Goal?" })).toBeDisabled();
  first.unmount();
  render(<ClarificationCard {...props} />);
  expect(screen.getByRole("textbox", { name: "Goal?" })).toHaveValue("");
  expect(screen.getByRole("radio", { name: "B" })).not.toBeChecked();
  expect(
    screen.queryByRole("button", { name: "Submitted" })
  ).not.toBeInTheDocument();
});

it("retains answers after rejection and permits retry", async () => {
  const submit = vi
    .fn()
    .mockRejectedValueOnce(new Error("Conflict"))
    .mockResolvedValue(undefined);
  render(
    <ClarificationCard {...props} initialAnswers={answers} onSubmit={submit} />
  );
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Conflict");
  expect(screen.getByRole("textbox", { name: "Goal?" })).toHaveValue(
    "Saved goal"
  );
  expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Submitted" })).toBeDisabled()
  );
  expect(submit).toHaveBeenCalledTimes(2);
});

it("replays only valid responses matching the form and unit", () => {
  const response = parseClarificationResponse({
    schema_version: 1,
    source_message_id: 10,
    unit_index: 7,
    form,
    answers,
  })!;
  expect(response).not.toBeNull();
  const parts: { type: string; name?: string; data?: unknown }[] = [];
  appendClarificationPart(parts, form, 7, true, response);
  expect(parts[0].data).toMatchObject({ submitted: true, answers });
  const reordered = {
    ...form,
    questions: form.questions.map((question) => ({
      ...question,
      options: question.options.map((option) => ({
        label: option.label,
        id: option.id,
      })),
    })),
  };
  appendClarificationPart(parts, reordered, 7, true, response);
  expect(parts[0].data).toMatchObject({ submitted: true, answers });
  appendClarificationPart(parts, form, 8, true, response);
  expect(parts[1].data).not.toHaveProperty("submitted");
  expect(
    parseClarificationResponse({ ...response, answers: [answers[0]] })
  ).toBeNull();
  expect(
    parseClarificationResponse({ ...response, source_message_id: -1 })
  ).toBeNull();
  expect(
    parseClarificationResponse({
      ...response,
      answers: [answers[0], { ...answers[1], value: "forged" }, answers[2]],
    })
  ).toBeNull();
  expect(parseClarificationResponse(null)).toBeNull();
});
