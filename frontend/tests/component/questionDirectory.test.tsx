// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  collectQuestionDirectory,
  scrollThreadToMessage,
  useActiveQuestionId,
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
  overrides: Record<string, unknown> = {},
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

test("collectQuestionDirectory attaches and caps the assistant reply excerpt", () => {
  const longReply = "回".repeat(450);
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user", { content: [{ type: "text", text: "第一问" }] }),
    makeMessage("a1", "assistant", { content: [{ type: "tool" }] }),
    makeMessage("a2", "assistant", {
      content: [{ type: "text", text: longReply }],
    }),
    makeMessage("u2", "user", { content: [{ type: "text", text: "第二问" }] }),
  ]);

  // Text-free assistant messages (tool calls, reasoning) do not consume the
  // pending reply; the first textual reply wins and is capped at the limit.
  expect(questions[0]?.replyText).toHaveLength(400);
  expect(questions[0]?.replyText?.endsWith("…")).toBe(true);
  // A trailing question without any reply keeps an empty excerpt.
  expect(questions[1]?.replyText).toBe("");
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

test("useActiveQuestionId tracks the last question above the viewport midline", async () => {
  const first = document.createElement("div");
  first.setAttribute("data-message-id", "u1");
  const second = document.createElement("div");
  second.setAttribute("data-message-id", "u2");
  document.body.append(first, second);

  const makeRect = (top: number) =>
    ({
      top,
      right: 0,
      bottom: 0,
      left: 0,
      width: 0,
      height: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect;

  const getRectSpy = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      // jsdom viewport height is 768, so the midline sits at 384.
      return makeRect(this === first ? 100 : 500);
    });

  const questions = collectQuestionDirectory([
    makeMessage("u1", "user", { content: [{ type: "text", text: "第一问" }] }),
    makeMessage("u2", "user", { content: [{ type: "text", text: "第二问" }] }),
  ]);
  const { result, unmount } = renderHook(() => useActiveQuestionId(questions));

  // Initial computation: only the first question sits above the midline.
  await waitFor(() => expect(result.current).toBe("u1"));

  // Scrolling the second question above the midline switches the marker.
  getRectSpy.mockImplementation(function (this: HTMLElement) {
    return makeRect(this === first ? 100 : 200);
  });
  window.dispatchEvent(new Event("scroll"));
  await waitFor(() => expect(result.current).toBe("u2"));

  unmount();
  getRectSpy.mockRestore();
});

const renderDirectoryButton = (
  props: Partial<Parameters<typeof QuestionDirectoryButton>[0]> = {},
) =>
  render(
    <TooltipProvider>
      <QuestionDirectoryButton
        questions={collectQuestionDirectory([
          makeMessage("u1", "user", {
            content: [{ type: "text", text: "第一问是什么" }],
          }),
          makeMessage("a1", "assistant", {
            content: [
              { type: "text", text: "这是第一问的回答,用于悬停预览。" },
            ],
          }),
          makeMessage("u2", "user", {
            content: [{ type: "file", filename: "data.csv" }],
            attachments: [{ name: "data.csv" }],
          }),
        ])}
        onJump={() => {}}
        {...props}
      />
    </TooltipProvider>,
  );

test("QuestionDirectoryButton hides without questions", () => {
  const { container } = render(
    <TooltipProvider>
      <QuestionDirectoryButton questions={[]} onJump={() => {}} />
    </TooltipProvider>,
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
    screen.getByRole("button", { name: "chat.questions.jump:1" }),
  );

  expect(onJump).toHaveBeenCalledWith("u1");
  // Clicking an entry closes the popover.
  await waitFor(() => expect(screen.queryByText("第一问是什么")).toBeNull());
});

test("QuestionDirectoryButton filters questions by keyword", async () => {
  renderDirectoryButton();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
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
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
  );
  const searchBox = await screen.findByRole("textbox", {
    name: "chat.questions.search",
  });

  fireEvent.change(searchBox, { target: { value: "不存在的关键词" } });

  await waitFor(() =>
    expect(screen.getByTestId("question-directory-no-matches")).toBeTruthy(),
  );
  expect(screen.queryByText("第一问是什么")).toBeNull();
  expect(screen.queryByText("data.csv")).toBeNull();
});

test("QuestionDirectoryButton resets the keyword when the popover closes", async () => {
  renderDirectoryButton();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
  );
  const searchBox = await screen.findByRole("textbox", {
    name: "chat.questions.search",
  });
  fireEvent.change(searchBox, { target: { value: "data" } });
  await waitFor(() => expect(screen.getByText("data.csv")).toBeTruthy());

  // Close via the trigger; reopening must show the unfiltered directory again.
  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
  );
  await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
  );

  await waitFor(() => expect(screen.getByText("第一问是什么")).toBeTruthy());
  expect(screen.getByText("data.csv")).toBeTruthy();
});

test("QuestionDirectoryButton marks the current question row", async () => {
  renderDirectoryButton({ activeMessageId: "u1" });

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
  );

  const activeRow = await screen.findByRole("button", {
    name: "chat.questions.jump:1",
  });
  expect(activeRow.getAttribute("aria-current")).toBe("location");
  expect(screen.getByTestId("question-directory-active").textContent).toBe(
    "chat.questions.current",
  );

  const otherRow = screen.getByRole("button", {
    name: "chat.questions.jump:2",
  });
  expect(otherRow.getAttribute("aria-current")).toBeNull();
});

test("QuestionDirectoryButton previews the question and reply on hover", async () => {
  renderDirectoryButton();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
  );
  const row = await screen.findByRole("button", {
    name: "chat.questions.jump:1",
  });

  fireEvent.mouseEnter(row);

  const card = await screen.findByTestId("question-directory-preview");
  expect(card.textContent).toContain("第一问是什么");
  expect(card.textContent).toContain("这是第一问的回答,用于悬停预览。");

  fireEvent.mouseLeave(row);
  await waitFor(() =>
    expect(screen.queryByTestId("question-directory-preview")).toBeNull(),
  );
});

test("QuestionDirectoryButton previews a question without a reply on hover", async () => {
  renderDirectoryButton();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.questions.viewAll:2" }),
  );
  const row = await screen.findByRole("button", {
    name: "chat.questions.jump:2",
  });

  fireEvent.mouseEnter(row);

  const card = await screen.findByTestId("question-directory-preview");
  expect(card.textContent).toContain("data.csv");
  expect(card.textContent).toContain("chat.questions.noReply");
});
