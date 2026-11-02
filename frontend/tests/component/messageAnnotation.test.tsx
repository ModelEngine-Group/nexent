// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import {
  createMessageAnnotation,
  formatAnnotationsIntoMessage,
  getAnnotationSourceExcerpt,
  resolveAnnotationSelection,
  truncateAnnotationText,
  type AnnotationMessageLabels,
  type MessageAnnotation,
} from "@/app/newchat/utils/message-annotations";
import { ComposerAnnotationChip } from "@/app/newchat/assistant-ui/annotation-chip";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const LABELS: AnnotationMessageLabels = {
  quoteLabel: "Quote",
  sourceLabel: ' (from reply "{{excerpt}}")',
  commentLabel: "Comment",
  colon: ": ",
};

const makeAnnotation = (
  overrides: Partial<MessageAnnotation> = {}
): MessageAnnotation => ({
  id: "annotation-1",
  quotedText: "quoted reply text",
  comment: undefined,
  sourceMessageId: "assistant-1",
  sourceExcerpt: "reply intro",
  ...overrides,
});

afterEach(cleanup);

describe("formatAnnotationsIntoMessage", () => {
  test("returns the text unchanged without annotations", () => {
    expect(formatAnnotationsIntoMessage("why stop?", [], LABELS)).toBe(
      "why stop?"
    );
    expect(formatAnnotationsIntoMessage("", [], LABELS)).toBe("");
  });

  test("composes a single annotation with comment and source excerpt", () => {
    const result = formatAnnotationsIntoMessage(
      "why stop?",
      [
        makeAnnotation({
          quotedText: "line one\nline two",
          comment: "skip this",
          sourceExcerpt: "reply intro",
        }),
      ],
      LABELS
    );

    expect(result).toBe(
      '1. Quote (from reply "reply intro"):\n> line one\n> line two\nComment: skip this\n\n---\n\nwhy stop?'
    );
  });

  test("composes multiple annotations, skipping empty comments and excerpts", () => {
    const result = formatAnnotationsIntoMessage(
      "follow-up",
      [
        makeAnnotation({ id: "a1", comment: "note" }),
        makeAnnotation({
          id: "a2",
          quotedText: "second",
          comment: undefined,
          sourceExcerpt: "",
        }),
      ],
      LABELS
    );

    expect(result).toBe(
      '1. Quote (from reply "reply intro"):\n> quoted reply text\nComment: note\n\n2. Quote:\n> second\n\n---\n\nfollow-up'
    );
  });

  test("composes annotation-only sends without the user separator", () => {
    const result = formatAnnotationsIntoMessage(
      "",
      [makeAnnotation({ comment: undefined })],
      LABELS
    );

    expect(result).toBe(
      '1. Quote (from reply "reply intro"):\n> quoted reply text'
    );
  });
});

describe("truncateAnnotationText", () => {
  test("keeps short text and collapses whitespace", () => {
    expect(truncateAnnotationText("  hello   world  ", 20)).toBe("hello world");
  });

  test("truncates long text with an ellipsis at the limit", () => {
    expect(truncateAnnotationText("abcdefghij", 4)).toBe("abc…");
    expect(truncateAnnotationText("abcdefghij", 10)).toBe("abcdefghij");
    expect(truncateAnnotationText("   ", 10)).toBe("");
  });
});

describe("getAnnotationSourceExcerpt", () => {
  test("joins text parts of the assistant message and skips other parts", () => {
    const messages = [
      {
        id: "user-1",
        role: "user",
        content: [{ type: "text", text: "question" }],
      },
      {
        id: "assistant-1",
        role: "assistant",
        content: [
          { type: "reasoning", text: "thinking" },
          { type: "text", text: "first " },
          { type: "text", text: "second" },
          { type: "tool-call" },
        ],
      },
    ];

    expect(getAnnotationSourceExcerpt(messages, "assistant-1")).toBe(
      "first second"
    );
  });

  test("returns an empty excerpt for user or unknown messages", () => {
    const messages = [
      {
        id: "user-1",
        role: "user",
        content: [{ type: "text", text: "question" }],
      },
    ];

    expect(getAnnotationSourceExcerpt(messages, "user-1")).toBe("");
    expect(getAnnotationSourceExcerpt(messages, "missing")).toBe("");
  });

  test("truncates long replies to the excerpt limit", () => {
    const long = "x".repeat(60);
    const messages = [
      {
        id: "assistant-1",
        role: "assistant",
        content: [{ type: "text", text: long }],
      },
    ];

    const excerpt = getAnnotationSourceExcerpt(messages, "assistant-1");
    expect(excerpt).toHaveLength(40);
    expect(excerpt.endsWith("…")).toBe(true);
  });
});

describe("createMessageAnnotation", () => {
  test("uses the given id, trims the comment and resolves the excerpt", () => {
    const messages = [
      {
        id: "assistant-1",
        role: "assistant",
        content: [{ type: "text", text: "reply intro text" }],
      },
    ];

    const annotation = createMessageAnnotation(
      {
        quotedText: "  quoted  ",
        comment: "  keep this  ",
        sourceMessageId: "assistant-1",
      },
      messages,
      "generated-id"
    );

    expect(annotation).toEqual({
      id: "generated-id",
      quotedText: "  quoted  ",
      comment: "keep this",
      sourceMessageId: "assistant-1",
      sourceExcerpt: "reply intro text",
    });
  });

  test("drops whitespace-only comments", () => {
    const annotation = createMessageAnnotation(
      { quotedText: "q", comment: "   ", sourceMessageId: "assistant-1" },
      [],
      "generated-id"
    );

    expect(annotation.comment).toBeUndefined();
  });
});

describe("resolveAnnotationSelection", () => {
  const buildAssistantMessage = (id: string) => {
    const root = document.createElement("div");
    root.setAttribute("data-role", "assistant");
    root.setAttribute("data-message-id", id);
    const content = document.createElement("div");
    content.setAttribute("data-slot", "aui_assistant-message-content");
    const paragraph = document.createElement("p");
    paragraph.textContent = "quotable text here";
    content.appendChild(paragraph);
    root.appendChild(content);
    const chain = document.createElement("div");
    chain.setAttribute("data-slot", "aui_chain-of-thought");
    const chainText = document.createElement("span");
    chainText.textContent = "reasoning content";
    chain.appendChild(chainText);
    root.appendChild(chain);
    const toolGroup = document.createElement("div");
    toolGroup.className = "aui-tool-group-root";
    const toolText = document.createElement("span");
    toolText.textContent = "tool content";
    toolGroup.appendChild(toolText);
    root.appendChild(toolGroup);
    document.body.appendChild(root);
    return { root, paragraph, chainText, toolText };
  };

  const makeSelection = (
    anchorNode: Node,
    focusNode: Node,
    text: string,
    isCollapsed = false
  ) =>
    ({
      isCollapsed,
      rangeCount: 1,
      anchorNode,
      focusNode,
      toString: () => text,
      getRangeAt: () => document.createRange(),
    }) as unknown as Selection;

  test("resolves a selection inside one assistant message", () => {
    const { paragraph } = buildAssistantMessage("assistant-1");
    const textNode = paragraph.firstChild as Node;

    const target = resolveAnnotationSelection(
      makeSelection(textNode, textNode, "quotable text")
    );

    expect(target).not.toBeNull();
    expect(target?.messageId).toBe("assistant-1");
    expect(target?.text).toBe("quotable text");
    expect(target?.range).toBeInstanceOf(Range);
  });

  test("rejects collapsed and empty selections", () => {
    const { paragraph } = buildAssistantMessage("assistant-1");
    const textNode = paragraph.firstChild as Node;

    expect(
      resolveAnnotationSelection(
        makeSelection(textNode, textNode, "quotable", true)
      )
    ).toBeNull();
    expect(
      resolveAnnotationSelection(makeSelection(textNode, textNode, "   "))
    ).toBeNull();
    expect(resolveAnnotationSelection(null)).toBeNull();
  });

  test("rejects selections inside reasoning and tool containers", () => {
    const { paragraph, chainText, toolText } =
      buildAssistantMessage("assistant-1");
    const contentNode = paragraph.firstChild as Node;
    const chainNode = chainText.firstChild as Node;
    const toolNode = toolText.firstChild as Node;

    expect(
      resolveAnnotationSelection(
        makeSelection(chainNode, chainNode, "reasoning content")
      )
    ).toBeNull();
    expect(
      resolveAnnotationSelection(
        makeSelection(toolNode, toolNode, "tool content")
      )
    ).toBeNull();
    // Spans from the reply content into a reasoning block.
    expect(
      resolveAnnotationSelection(
        makeSelection(contentNode, chainNode, "crossing")
      )
    ).toBeNull();
  });

  test("rejects selections outside or across assistant messages", () => {
    const { paragraph } = buildAssistantMessage("assistant-1");
    const other = buildAssistantMessage("assistant-2");
    const userMessage = document.createElement("div");
    userMessage.setAttribute("data-role", "user");
    const userText = document.createElement("p");
    userText.textContent = "user text";
    userMessage.appendChild(userText);
    document.body.appendChild(userMessage);

    const contentNode = paragraph.firstChild as Node;
    const otherNode = other.paragraph.firstChild as Node;
    const userNode = userText.firstChild as Node;

    // Endpoints in two different messages.
    expect(
      resolveAnnotationSelection(makeSelection(contentNode, otherNode, "two"))
    ).toBeNull();
    // User message selection.
    expect(
      resolveAnnotationSelection(makeSelection(userNode, userNode, "user text"))
    ).toBeNull();
  });
});

describe("ComposerAnnotationChip", () => {
  const baseAnnotations = (): MessageAnnotation[] => [
    makeAnnotation({
      id: "a1",
      quotedText: "first quote",
      comment: "first note",
    }),
    makeAnnotation({
      id: "a2",
      quotedText: "second quote",
      comment: undefined,
    }),
  ];

  const renderChip = (annotations: MessageAnnotation[]) =>
    render(
      <ComposerAnnotationChip
        annotations={annotations}
        onEditComment={vi.fn()}
        onRemove={vi.fn()}
        onClear={vi.fn()}
      />
    );

  test("renders nothing without annotations", () => {
    const { container } = renderChip([]);
    expect(container.firstChild).toBeNull();
  });

  test("opens the annotation list on hover and lists every entry", () => {
    renderChip(baseAnnotations());

    const trigger = screen.getByText("chat.annotation.chipLabel");
    fireEvent.mouseEnter(trigger);

    const list = screen.getByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText(/first quote/)).toBeTruthy();
    expect(within(items[0]).getByText(/first note/)).toBeTruthy();
    expect(within(items[1]).getByText(/second quote/)).toBeTruthy();
  });

  test("removes a single annotation from the list", () => {
    const onRemove = vi.fn();
    render(
      <ComposerAnnotationChip
        annotations={baseAnnotations()}
        onEditComment={vi.fn()}
        onRemove={onRemove}
        onClear={vi.fn()}
      />
    );

    fireEvent.mouseEnter(screen.getByText("chat.annotation.chipLabel"));
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "chat.annotation.deleteAnnotation",
      })[0]
    );

    expect(onRemove).toHaveBeenCalledWith("a1");
  });

  test("clears all annotations from the chip", () => {
    const onClear = vi.fn();
    render(
      <ComposerAnnotationChip
        annotations={baseAnnotations()}
        onEditComment={vi.fn()}
        onRemove={vi.fn()}
        onClear={onClear}
      />
    );

    fireEvent.click(
      screen.getByRole("button", { name: "chat.annotation.clearAnnotations" })
    );

    expect(onClear).toHaveBeenCalledTimes(1);
  });

  test("edits a comment inline and saves the trimmed value", () => {
    const onEditComment = vi.fn();
    render(
      <ComposerAnnotationChip
        annotations={baseAnnotations()}
        onEditComment={onEditComment}
        onRemove={vi.fn()}
        onClear={vi.fn()}
      />
    );

    fireEvent.mouseEnter(screen.getByText("chat.annotation.chipLabel"));
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "chat.annotation.editComment",
      })[0]
    );

    const input = screen.getByLabelText("chat.annotation.editPlaceholder");
    fireEvent.change(input, { target: { value: "  updated note  " } });
    fireEvent.click(
      screen.getByRole("button", { name: "chat.annotation.saveComment" })
    );

    expect(onEditComment).toHaveBeenCalledWith("a1", "updated note");
  });

  test("cancels editing without saving", () => {
    const onEditComment = vi.fn();
    render(
      <ComposerAnnotationChip
        annotations={baseAnnotations()}
        onEditComment={onEditComment}
        onRemove={vi.fn()}
        onClear={vi.fn()}
      />
    );

    fireEvent.mouseEnter(screen.getByText("chat.annotation.chipLabel"));
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "chat.annotation.editComment",
      })[0]
    );
    fireEvent.click(
      screen.getByRole("button", { name: "chat.annotation.cancelEdit" })
    );

    expect(onEditComment).not.toHaveBeenCalled();
    // The edit entry point is rendered again after cancelling.
    expect(
      screen.getAllByRole("button", { name: "chat.annotation.editComment" })
        .length
    ).toBeGreaterThan(0);
  });
});
