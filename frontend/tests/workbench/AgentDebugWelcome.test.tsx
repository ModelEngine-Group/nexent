// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AgentDebugWelcome } from "@/app/agents/[agentId]/components/debug/agent-debug-welcome";
import type { Agent } from "@/types/agentConfig";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { agent: { icon: (id: number) => `/fixture/icon/${id}` } },
}));

const agent = {
  id: "42",
  name: "Internal name",
  display_name: "Draft name",
  greeting_message: "Draft greeting",
  description: "Fallback description",
  example_questions: Object.freeze(
    Array.from({ length: 6 }, (_, index) => `Question ${index + 1}`)
  ),
} as unknown as Agent;

it("composes the welcome and all legacy questions together with callback-only selection", () => {
  const onSelectQuestion = vi.fn();
  render(
    <AgentDebugWelcome agent={agent} onSelectQuestion={onSelectQuestion} />
  );
  const welcome = within(screen.getByTestId("agent-debug-welcome"));
  expect(
    welcome.getByRole("heading", { name: "Draft name" })
  ).toBeInTheDocument();
  expect(welcome.getByText("Draft greeting")).toBeInTheDocument();
  expect(
    welcome.getByRole("heading", { name: "agentSuggestion.heading" })
  ).toBeInTheDocument();
  expect(welcome.getAllByRole("button")).toHaveLength(6);
  fireEvent.click(welcome.getByRole("button", { name: "Question 6" }));
  expect(onSelectQuestion).toHaveBeenCalledExactlyOnceWith("Question 6");
  expect(agent.example_questions).toHaveLength(6);
});

it("skips blank preset questions when rendering suggestion buttons", () => {
  const onSelectQuestion = vi.fn();
  render(
    <AgentDebugWelcome
      agent={{
        ...agent,
        example_questions: ["Real question", "", "   ", "Another real one"],
      }}
      onSelectQuestion={onSelectQuestion}
    />
  );
  const welcome = within(screen.getByTestId("agent-debug-welcome"));
  expect(welcome.getAllByRole("button")).toHaveLength(2);
  expect(
    welcome.getByRole("button", { name: "Real question" })
  ).toBeInTheDocument();
  expect(
    welcome.getByRole("button", { name: "Another real one" })
  ).toBeInTheDocument();
  fireEvent.click(welcome.getByRole("button", { name: "Real question" }));
  expect(onSelectQuestion).toHaveBeenCalledExactlyOnceWith("Real question");
});

it("renders no suggestion section when every preset question is blank", () => {
  render(
    <AgentDebugWelcome
      agent={{ ...agent, example_questions: ["", "   "] }}
      onSelectQuestion={vi.fn()}
    />
  );
  expect(
    screen.queryByTestId("agent-debug-suggestions")
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("blocks selection during a run and restores it without replacing welcome content", () => {
  const onSelectQuestion = vi.fn();
  const view = render(
    <AgentDebugWelcome
      agent={agent}
      onSelectQuestion={onSelectQuestion}
      disabled
    />
  );
  const welcome = screen.getByTestId("agent-debug-welcome");
  for (const button of within(welcome).getAllByRole("button")) {
    expect(button).toBeDisabled();
    fireEvent.click(button);
  }
  expect(onSelectQuestion).not.toHaveBeenCalled();
  view.rerender(
    <AgentDebugWelcome agent={agent} onSelectQuestion={onSelectQuestion} />
  );
  expect(screen.getByTestId("agent-debug-welcome")).toBe(welcome);
  fireEvent.click(screen.getByRole("button", { name: "Question 1" }));
  expect(onSelectQuestion).toHaveBeenCalledExactlyOnceWith("Question 1");
});

it("keeps fallback identity and greeting with no empty question heading", () => {
  render(
    <AgentDebugWelcome
      agent={{
        ...agent,
        display_name: "",
        greeting_message: "",
        example_questions: [],
      }}
      onSelectQuestion={vi.fn()}
    />
  );
  expect(
    screen.getByRole("heading", { name: "Internal name" })
  ).toBeInTheDocument();
  expect(screen.getByText("Fallback description")).toBeInTheDocument();
  expect(
    screen.queryByTestId("agent-debug-suggestions")
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
