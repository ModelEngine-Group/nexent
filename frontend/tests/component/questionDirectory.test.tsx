// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  collectQuestionDirectory,
  scrollThreadToMessage,
  type QuestionMessageLike,
} from "@/app/newchat/utils/question-directory";
import { QuestionDirectoryButton } from "@/app/newchat/ui/question-directory";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (params && "count" in params) return `${key}:${params.count}`;
      if (params && "index" in params) return `${key}:${params.index}`;
      return key;
    },
  }),
}));

vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn(), warn: vi.fn(), log: vi.fn() },
}));

const makeMessage = (
  id: string,
  role: string,
  overrides: Record<string, unknown> = {}
): QuestionMessageLike =>
  ({
    id,
    role,
    content: [{ type: "text", text: `question ${id}` }],
    ...overrides,
  }) as QuestionMessageLike;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  document.body.innerHTML = "";
});

test("collectQuestionDirectory extracts user questions in order", () => {
  const messages: QuestionMessageLike[] = [
    makeMessage("u1", "user", {
      content: [{ type: "text", text: "第一问" }],
    }),
    makeMessage("a1", "assistant"),
    makeMessage("u2", "user", {
      content: [{ type: "text", text: "第二问" }],
    }),
  ];

  const questions = collectQuestionDirectory(messages);

  expect(questions).toHaveLength(2);
  expect(questions[0]).toMatchObject({
    key: "u1",
    messageId: "u1",
    index: 1,
    summary: "第一问",
    kind: "text",
  });
  expect(questions[1]).toMatchObject({
    key: "u2",
    messageId: "u2",
    index: 2,
    kind: "text",
  });
});

test("collectQuestionDirectory uses the first line and truncates long questions", () => {
  const longQuestion = `第一行超长问题${"很".repeat(80)}，后面还有第二行`;
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user", {
      content: [{ type: "text", text: `${longQuestion}\nsecond line` }],
    }),
  ]);

  expect(questions).toHaveLength(1);
  expect(questions[0]?.summary.startsWith("第一行超长问题")).toBe(true);
  expect(questions[0]?.summary.length).toBeLessThanOrEqual(60);
  expect(questions[0]?.summary.endsWith("…")).toBe(true);
  // The full multi-line text is preserved for the tooltip.
  expect(questions[0]?.fullText).toContain("second line");
});

test("collectQuestionDirectory falls back to the first attachment name", () => {
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user", {
      content: [{ type: "file", filename: "data.csv" }],
      attachments: [{ name: "data.csv" }, { name: "extra.txt" }],
    }),
  ]);

  expect(questions).toHaveLength(1);
  expect(questions[0]).toMatchObject({
    kind: "attachment",
    summary: "data.csv",
    fullText: "data.csv",
  });
});

test("collectQuestionDirectory skips empty and non-user messages", () => {
  const questions = collectQuestionDirectory([
    makeMessage("a1", "assistant"),
    makeMessage("u1", "user", { content: [], attachments: [] }),
    makeMessage("u2", "user", {
      content: [{ type: "text", text: "  " }],
    }),
  ]);

  expect(questions).toEqual([]);
});

test("scrollThreadToMessage scrolls to and highlights the target message", () => {
  const element = document.createElement("div");
  element.setAttribute("data-message-id", "msg-42");
  const scrollIntoView = vi.fn();
  element.scrollIntoView = scrollIntoView;
  document.body.appendChild(element);

  const found = scrollThreadToMessage("msg-42");

  expect(found).toBe(true);
  expect(scrollIntoView).toHaveBeenCalledWith({
    behavior: "smooth",
    block: "start",
  });
  expect(element.style.boxShadow).not.toBe("");
});

test("scrollThreadToMessage reports missing targets", () => {
  expect(scrollThreadToMessage("missing")).toBe(false);
  expect(scrollThreadToMessage("")).toBe(false);
});

const renderDirectoryButton = (
  props: Partial<Parameters<typeof QuestionDirectoryButton>[0]> = {}
) =>
  render(
    <TooltipProvider>
      <QuestionDirectoryButton
        questions={collectQuestionDirectory([
          makeMessage("u1", "user", {
            content: [{ type: "text", text: "第一问是什么" }],
          }),
          makeMessage("u2", "user", {
            content: [{ type: "file", filename: "data.csv" }],
            attachments: [{ name: "data.csv" }],
          }),
        ])}
        onJump={() => {}}
        {...props}
      />
    </TooltipProvider>
  );

test("QuestionDirectoryButton hides without questions", () => {
  const { container } = render(
    <TooltipProvider>
      <QuestionDirectoryButton questions={[]} onJump={() => {}} />
    </TooltipProvider>
  );

  expect(container.firstChild).toBeNull();
});

test("QuestionDirectoryButton lists questions and jumps on click", async () => {
  const onJump = vi.fn();
  renderDirectoryButton({ onJump });

  // The trigger shows the question count.
  const trigger = screen.getByRole("button", {
    name: "chat.questions.viewAll:2",
  });
  fireEvent.click(trigger);

  // The popover lists both questions with jump affordances.
  expect(await screen.findByText("第一问是什么")).toBeTruthy();
  expect(screen.getByText("data.csv")).toBeTruthy();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.jump:1" })
  );

  expect(onJump).toHaveBeenCalledWith("u1");
  // Clicking an entry closes the popover.
  await waitFor(() => expect(screen.queryByText("第一问是什么")).toBeNull());
});

test("QuestionDirectoryButton filters questions by keyword", async () => {
  renderDirectoryButton();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" })
  );
  const searchBox = await screen.findByRole("textbox", {
    name: "chat.questions.search",
  });

  fireEvent.change(searchBox, { target: { value: "第一问" } });
  await waitFor(() => expect(screen.getByText("第一问是什么")).toBeTruthy());
  expect(screen.queryByText("data.csv")).toBeNull();

  // Filtering is case-insensitive and matches attachment turns.
  fireEvent.change(searchBox, { target: { value: "DATA" } });
  await waitFor(() => expect(screen.getByText("data.csv")).toBeTruthy());
  expect(screen.queryByText("第一问是什么")).toBeNull();
});

test("QuestionDirectoryButton shows an empty state for unmatched keywords", async () => {
  renderDirectoryButton();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" })
  );
  const searchBox = await screen.findByRole("textbox", {
    name: "chat.questions.search",
  });

  fireEvent.change(searchBox, { target: { value: "不存在的关键词" } });

  await waitFor(() =>
    expect(screen.getByTestId("question-directory-no-matches")).toBeTruthy()
  );
  expect(screen.queryByText("第一问是什么")).toBeNull();
  expect(screen.queryByText("data.csv")).toBeNull();
});

test("QuestionDirectoryButton resets the keyword when the popover closes", async () => {
  renderDirectoryButton();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" })
  );
  const searchBox = await screen.findByRole("textbox", {
    name: "chat.questions.search",
  });
  fireEvent.change(searchBox, { target: { value: "data" } });
  await waitFor(() => expect(screen.getByText("data.csv")).toBeTruthy());

  // Close via the trigger; reopening must show the unfiltered directory again.
  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" })
  );
  await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" })
  );

  await waitFor(() => expect(screen.getByText("第一问是什么")).toBeTruthy());
  expect(screen.getByText("data.csv")).toBeTruthy();
});
