import { App, Form } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentGuide from "../../../frontend/app/[locale]/agents/[agentId]/components/agent-guide";

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  t: vi.fn((key: string, options?: unknown) =>
    options ? `${key}:${JSON.stringify(options)}` : key,
  ),
  draft: { greeting_message: "", example_questions: [] as string[] },
}));

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: unknown) => unknown) =>
    selector({
      editedAgent: mocks.draft,
      updateAgentConfig: mocks.update,
    }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => false,
}));

function guideTree(highFidelity = true) {
  return (
    <App>
      <Form>
        <AgentGuide highFidelity={highFidelity} />
      </Form>
    </App>
  );
}

const addButton = () =>
  screen.getByRole("button", {
    name: /agent\.highFidelity\.addPresetQuestion/,
  });
const questionInputs = () =>
  screen.getAllByPlaceholderText("agent.guide.example.placeholder");

describe("AGENT-CONFIG-D1-002 five-question additions and legacy preservation", () => {
  beforeEach(() => {
    mocks.draft = { greeting_message: "", example_questions: [] };
    mocks.update.mockReset();
    mocks.t.mockClear();
  });

  it("uses maximum five and preserves greeting/question edits from an empty draft", () => {
    const view = render(guideTree());
    expect(screen.getByText("(0/5)")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("agent.highFidelity.questionPlaceholder"),
    ).not.toBeInTheDocument();
    fireEvent.click(addButton());
    expect(mocks.update).toHaveBeenCalledWith({ example_questions: [""] });
    mocks.draft.example_questions = [""];
    view.rerender(guideTree());
    expect(questionInputs()[0]).toHaveClass(
      "!h-8",
      "!w-[564px]",
      "!max-w-full",
    );
    fireEvent.change(questionInputs()[0], {
      target: { value: "What can this Agent do?" },
    });
    expect(mocks.update).toHaveBeenCalledWith({
      example_questions: ["What can this Agent do?"],
    });
    fireEvent.change(
      screen.getByPlaceholderText("agent.highFidelity.greetingPlaceholder"),
      { target: { value: "Welcome" } },
    );
    expect(mocks.update).toHaveBeenCalledWith({ greeting_message: "Welcome" });
    expect(mocks.t).toHaveBeenCalledWith(
      "agent.validation.exampleQuestionsMax",
      { max: 5 },
    );
  });

  it("adds only the fifth question and re-enables addition after removal", () => {
    mocks.draft.example_questions = ["one", "two", "three", "four"];
    const view = render(guideTree());
    fireEvent.click(addButton());
    expect(mocks.update).toHaveBeenLastCalledWith({
      example_questions: ["one", "two", "three", "four", ""],
    });
    mocks.draft.example_questions = ["one", "two", "three", "four", "five"];
    view.rerender(guideTree());
    expect(addButton()).toBeDisabled();
    expect(screen.getByText("(5/5)")).toBeInTheDocument();
    mocks.update.mockClear();
    fireEvent.click(addButton());
    expect(mocks.update).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "agent.guide.example.removeAria",
      })[1],
    );
    expect(mocks.update).toHaveBeenCalledWith({
      example_questions: ["one", "three", "four", "five"],
    });
    mocks.draft.example_questions = ["one", "three", "four", "five"];
    view.rerender(guideTree());
    expect(addButton()).not.toBeDisabled();
  });

  it("loads all six legacy values without a write or truncation", () => {
    mocks.draft.example_questions = [
      "one",
      "two",
      "three",
      "four",
      "five",
      "six",
    ];
    render(guideTree());
    expect(questionInputs()).toHaveLength(6);
    expect(
      questionInputs().map((input) => (input as HTMLInputElement).value),
    ).toEqual(mocks.draft.example_questions);
    expect(addButton()).toBeDisabled();
    expect(mocks.update).not.toHaveBeenCalled();
  });
});

describe("AGENT-CONFIG-D1-004 greeting text boundaries and compatibility", () => {
  beforeEach(() => {
    mocks.draft = { greeting_message: "", example_questions: [] };
    mocks.update.mockReset();
  });

  it("accepts the complete 200-character greeting and leaves question text unconstrained", () => {
    const view = render(guideTree());
    const greeting = screen.getByPlaceholderText(
      "agent.highFidelity.greetingPlaceholder",
    );
    expect(greeting).toHaveAttribute("maxlength", "200");
    const boundary = "g".repeat(200);
    fireEvent.change(greeting, { target: { value: boundary } });
    expect(mocks.update).toHaveBeenLastCalledWith({
      greeting_message: boundary,
    });
    expect(
      screen.queryByPlaceholderText("agent.highFidelity.questionPlaceholder"),
    ).not.toBeInTheDocument();
    fireEvent.click(addButton());
    mocks.draft.example_questions = [""];
    view.rerender(guideTree());
    const question = questionInputs()[0];
    expect(question).not.toHaveAttribute("maxlength");
    const longQuestion = "q".repeat(201);
    fireEvent.change(question, { target: { value: longQuestion } });
    expect(mocks.update).toHaveBeenLastCalledWith({
      example_questions: [longQuestion],
    });
  });

  it("preserves an overlong stored greeting and allows shortening without a load-time update", () => {
    const legacy = "g".repeat(201);
    mocks.draft.greeting_message = legacy;
    const view = render(guideTree());
    const greeting = screen.getByPlaceholderText(
      "agent.highFidelity.greetingPlaceholder",
    );
    expect(greeting).toHaveValue(legacy);
    expect(mocks.update).not.toHaveBeenCalled();
    fireEvent.change(greeting, { target: { value: "g".repeat(202) } });
    expect(mocks.update).not.toHaveBeenCalled();
    const shortened = "g".repeat(199);
    fireEvent.change(greeting, { target: { value: shortened } });
    expect(mocks.update).toHaveBeenLastCalledWith({
      greeting_message: shortened,
    });
    mocks.draft.greeting_message = shortened;
    view.rerender(guideTree());
    expect(greeting).toHaveAttribute("maxlength", "200");
  });

  it("keeps default greeting character behavior and the six-question limit", () => {
    mocks.draft.example_questions = ["one", "two", "three", "four", "five"];
    render(guideTree(false));
    expect(
      screen.getByPlaceholderText("agent.guide.opening.placeholder"),
    ).not.toHaveAttribute("maxlength");
    expect(screen.getByText("(5/6)")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "agent.greeting.addQuestion" }),
    );
    expect(mocks.update).toHaveBeenLastCalledWith({
      example_questions: ["one", "two", "three", "four", "five", ""],
    });
  });
});
