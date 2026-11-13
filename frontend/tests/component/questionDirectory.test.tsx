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
import { QuestionDirectoryRail } from "@/app/newchat/ui/question-directory-rail";

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

test("QuestionDirectoryRail hides for an empty conversation", () => {
  const { container } = render(
    <QuestionDirectoryRail questions={[]} onJump={vi.fn()} />
  );
  expect(container.firstChild).toBeNull();
});

test("QuestionDirectoryRail renders question ticks, marks current and jumps", () => {
  const onJump = vi.fn();
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user"),
    makeMessage("u2", "user"),
  ]);
  const { container } = render(
    <QuestionDirectoryRail
      questions={questions}
      onJump={onJump}
      activeMessageId="u2"
    />
  );
  const first = screen.getByRole("button", { name: "chat.questions.jump:1" });
  const second = screen.getByRole("button", { name: "chat.questions.jump:2" });
  expect(first.getAttribute("aria-current")).toBeNull();
  expect(second.getAttribute("aria-current")).toBe("location");
  expect(
    container.querySelectorAll('[data-slot="question-rail-current-dot"]')
  ).toHaveLength(1);
  fireEvent.click(first);
  expect(onJump).toHaveBeenCalledWith("u1");
});

test("QuestionDirectoryRail previews question and reply on keyboard focus", async () => {
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user"),
    makeMessage("a1", "assistant"),
  ]);
  render(<QuestionDirectoryRail questions={questions} onJump={vi.fn()} />);
  fireEvent.focus(
    screen.getByRole("button", { name: "chat.questions.jump:1" })
  );
  const preview = await screen.findByRole("tooltip");
  expect(preview.textContent).toContain("question u1");
  expect(preview.textContent).toContain("question a1");
});

test("QuestionDirectoryRail switches previews when moving from Q3 to adjacent Q2", async () => {
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user"),
    makeMessage("u2", "user"),
    makeMessage("u3", "user"),
  ]);
  render(
    <QuestionDirectoryRail
      questions={questions}
      onJump={vi.fn()}
      activeMessageId="u3"
    />
  );
  const second = screen.getByRole("button", { name: "chat.questions.jump:2" });
  const third = screen.getByRole("button", { name: "chat.questions.jump:3" });
  const rect = (x: number, y: number, width: number, height: number) =>
    ({
      x,
      y,
      width,
      height,
      top: y,
      left: x,
      right: x + width,
      bottom: y + height,
      toJSON: () => ({}),
    }) as DOMRect;
  const bounds = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      if (this === second) return rect(0, 15, 32, 15);
      if (this === third) return rect(0, 30, 32, 15);
      // A tall preview beside the ticks overlaps the diagonal hover corridor.
      if (this.getAttribute("role") === "tooltip") return rect(40, 0, 288, 300);
      return rect(0, 0, 0, 0);
    });
  try {
    fireEvent.pointerMove(third, {
      pointerType: "mouse",
      clientX: 31,
      clientY: 38,
    });
    expect((await screen.findByRole("tooltip")).textContent).toContain(
      "question u3"
    );
    fireEvent.pointerLeave(third, {
      pointerType: "mouse",
      clientX: 31,
      clientY: 30,
    });
    fireEvent.pointerMove(second, {
      pointerType: "mouse",
      clientX: 31,
      clientY: 25,
    });
    await waitFor(() => {
      const previews = screen.getAllByRole("tooltip");
      expect(previews).toHaveLength(1);
      expect(previews[0].textContent).toContain("question u2");
      expect(previews[0].textContent).not.toContain("question u3");
    });
    fireEvent.pointerLeave(second, {
      pointerType: "mouse",
      clientX: 0,
      clientY: 15,
    });
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  } finally {
    bounds.mockRestore();
  }
});

test("QuestionDirectoryRail has no expanded-directory entry or search popover", () => {
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user"),
    makeMessage("u2", "user"),
  ]);
  render(<QuestionDirectoryRail questions={questions} onJump={() => {}} />);
  expect(screen.getAllByRole("button")).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: "chat.questions.viewAll:2" })
  ).toBeNull();
  expect(
    screen.queryByRole("textbox", { name: "chat.questions.search" })
  ).toBeNull();
});

test("QuestionDirectoryRail keeps the active tick visible without scrolling chat", () => {
  const questions = collectQuestionDirectory([
    makeMessage("u1", "user"),
    makeMessage("u2", "user"),
  ]);
  const props = { questions, onJump: vi.fn() };
  const { container, rerender } = render(<QuestionDirectoryRail {...props} />);
  const list = container.querySelector("nav > div") as HTMLDivElement;
  const current = screen.getByRole("button", { name: "chat.questions.jump:2" });
  Object.defineProperties(list, {
    clientHeight: { value: 100 },
    offsetTop: { value: 80 },
  });
  Object.defineProperties(current, {
    offsetTop: { value: 300 },
    offsetHeight: { value: 15 },
  });
  const scrollIntoView = vi.mocked(HTMLElement.prototype.scrollIntoView);
  scrollIntoView.mockClear();
  rerender(<QuestionDirectoryRail {...props} activeMessageId="u2" />);
  expect(list.scrollTop).toBe(215);
  expect(scrollIntoView).not.toHaveBeenCalled();
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

test("scrollThreadToMessage scrolls to the target without a highlight frame", () => {
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
  expect(element.style.boxShadow).toBe("");
  expect(element.style.transition).toBe("");
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
