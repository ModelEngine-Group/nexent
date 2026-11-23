import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  AgentDebugSuggestions,
  AgentDebugWelcome,
} from "../../../frontend/app/[locale]/agents/[agentId]/components/debug/agent-debug-welcome";
import type { Agent } from "../../../frontend/types/agentConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { agent: { icon: (id: number) => `/fixture/icon/${id}` } },
}));

it("AGENT-DEBUG-D1-001 dynamic draft welcome and callback-only legacy question selection", () => {
  const questions = Object.freeze(
    Array.from({ length: 6 }, (_, index) => `Question ${index + 1}`),
  );
  const select = vi.fn();
  const agent = {
    id: "42",
    name: "Internal name",
    display_name: "Draft name",
    greeting_message: "Draft greeting",
    description: "Fallback description",
    example_questions: questions,
  } as unknown as Agent;
  const { rerender } = render(
    <>
      <AgentDebugWelcome agent={agent} />
      <AgentDebugSuggestions questions={questions} onSelect={select} />
    </>,
  );
  expect(
    screen.getByRole("heading", { name: "Draft name" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Draft greeting")).toBeInTheDocument();
  expect(screen.getAllByRole("button")).toHaveLength(6);
  expect(select).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Question 6" }));
  expect(select).toHaveBeenCalledExactlyOnceWith("Question 6");
  expect(questions).toEqual(
    Array.from({ length: 6 }, (_, index) => `Question ${index + 1}`),
  );
  rerender(
    <>
      <AgentDebugWelcome
        agent={{
          ...agent,
          display_name: "Changed name",
          greeting_message: "Changed greeting",
        }}
      />
      <AgentDebugSuggestions questions={[]} onSelect={select} />
    </>,
  );
  expect(
    screen.getByRole("heading", { name: "Changed name" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Changed greeting")).toBeInTheDocument();
  expect(
    screen.queryByTestId("agent-debug-suggestions"),
  ).not.toBeInTheDocument();
  expect(select).toHaveBeenCalledTimes(1);
  rerender(
    <AgentDebugWelcome
      agent={{ ...agent, display_name: "", greeting_message: "" }}
    />,
  );
  expect(
    screen.getByRole("heading", { name: "Internal name" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Fallback description")).toBeInTheDocument();
});
