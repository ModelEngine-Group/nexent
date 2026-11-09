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
  fromMessageAnnotationWireItems,
  getAnnotationSourceExcerpt,
  MESSAGE_ANNOTATION_COMMENT_MAX,
  MESSAGE_ANNOTATION_MAX_COUNT,
  MESSAGE_ANNOTATION_QUOTED_TEXT_MAX,
  resolveAnnotationSelection,
  toMessageAnnotationWireItems,
  truncateAnnotationText,
  type MessageAnnotation,
} from "@/app/newchat/utils/message-annotations";
import { ComposerAnnotationChip } from "@/app/newchat/assistant-ui/annotation-chip";
import { MessageAnnotationCards } from "@/app/newchat/assistant-ui/message-annotation-cards";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@assistant-ui/react", () => ({
  useAuiState: (selector: (state: unknown) => unknown) =>
    selector({ message: { role: "user" } }),
}));

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

describe("toMessageAnnotationWireItems", () => {
  test("drops legacy context from creation, outgoing and history mappings", () => {
    const annotation = createMessageAnnotation(
      {
        quotedText: "this approach",
        sourceMessageId: "assistant-1",
        contextBefore: "x".repeat(250) + "Redis ",
        contextAfter: " shares state." + "y".repeat(250),
      } as Parameters<typeof createMessageAnnotation>[0],
      [],
      "snapshot"
    );
    const wire = toMessageAnnotationWireItems([annotation]);
    expect(annotation).not.toHaveProperty("contextBefore");
    expect(annotation).not.toHaveProperty("contextAfter");
    expect(wire[0]).toEqual({
      quoted_text: "this approach",
      comment: null,
      source_excerpt: null,
    });
    const restored = fromMessageAnnotationWireItems([
      { ...wire[0], context_before: "old before", context_after: "old after" },
      { quoted_text: "q", context_before: 42, context_after: {} },
    ]);
    expect(restored).toEqual([
      wire[0],
      { quoted_text: "q", comment: null, source_excerpt: null },
    ]);
  });
  test("maps camelCase annotations onto the snake_case wire shape", () => {
    const items = toMessageAnnotationWireItems([
      makeAnnotation({ comment: "note", sourceExcerpt: "reply intro" }),
      makeAnnotation({
        id: "a2",
        quotedText: "second",
        comment: undefined,
        sourceExcerpt: "",
      }),
    ]);

    expect(items).toEqual([
      {
        quoted_text: "quoted reply text",
        comment: "note",
        source_excerpt: "reply intro",
      },
      { quoted_text: "second", comment: null, source_excerpt: null },
    ]);
  });

  test("caps the list length and truncates oversized fields", () => {
    const many = Array.from(
      { length: MESSAGE_ANNOTATION_MAX_COUNT + 3 },
      (_, i) => makeAnnotation({ id: `a${i}`, quotedText: `${i}` })
    );
    const items = toMessageAnnotationWireItems(many);
    expect(items).toHaveLength(MESSAGE_ANNOTATION_MAX_COUNT);

    const oversized = toMessageAnnotationWireItems([
      makeAnnotation({
        quotedText: "q".repeat(MESSAGE_ANNOTATION_QUOTED_TEXT_MAX + 10),
        comment: "c".repeat(MESSAGE_ANNOTATION_COMMENT_MAX + 10),
      }),
    ]);
    expect(oversized[0].quoted_text).toHaveLength(
      MESSAGE_ANNOTATION_QUOTED_TEXT_MAX
    );
    expect(oversized[0].comment).toHaveLength(MESSAGE_ANNOTATION_COMMENT_MAX);
  });
});

describe("fromMessageAnnotationWireItems", () => {
  test("validates entries and drops unusable ones", () => {
    const items = fromMessageAnnotationWireItems([
      { quoted_text: "one", comment: "note", source_excerpt: "intro" },
      { quoted_text: "   " },
      { quoted_text: "" },
      { comment: "no quote" },
      "not-an-object",
    ]);

    expect(items).toEqual([
      { quoted_text: "one", comment: "note", source_excerpt: "intro" },
    ]);
  });

  test("returns an empty list for non-array payloads", () => {
    expect(fromMessageAnnotationWireItems(undefined)).toEqual([]);
    expect(fromMessageAnnotationWireItems(null)).toEqual([]);
    expect(fromMessageAnnotationWireItems({ quoted_text: "x" })).toEqual([]);
  });

  test("re-applies the defensive caps for oversized persisted payloads", () => {
    const items = fromMessageAnnotationWireItems([
      {
        quoted_text: "q".repeat(MESSAGE_ANNOTATION_QUOTED_TEXT_MAX + 5),
        comment: null,
        source_excerpt: null,
      },
    ]);
    expect(items[0].quoted_text).toHaveLength(
      MESSAGE_ANNOTATION_QUOTED_TEXT_MAX
    );
  });

  test("round-trips payloads produced by the outgoing mapping", () => {
    const outgoing = toMessageAnnotationWireItems([
      makeAnnotation({ comment: "note" }),
    ]);
    expect(fromMessageAnnotationWireItems(outgoing)).toEqual(outgoing);
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

  test("applies the defensive caps to oversized quotes and comments", () => {
    const annotation = createMessageAnnotation(
      {
        quotedText: "q".repeat(MESSAGE_ANNOTATION_QUOTED_TEXT_MAX + 5),
        comment: "c".repeat(MESSAGE_ANNOTATION_COMMENT_MAX + 5),
        sourceMessageId: "assistant-1",
      },
      [],
      "generated-id"
    );

    expect(annotation.quotedText).toHaveLength(
      MESSAGE_ANNOTATION_QUOTED_TEXT_MAX
    );
    expect(annotation.comment).toHaveLength(MESSAGE_ANNOTATION_COMMENT_MAX);
  });
});

describe("resolveAnnotationSelection", () => {
  test("captures only the selected occurrence without surrounding paragraph text", () => {
    const root = document.createElement("div");
    root.dataset.role = "assistant";
    root.dataset.messageId = "a1";
    root.innerHTML = `<div data-slot="aui_assistant-message-content"><p>irrelevant intro</p><p>local cache: same. Redis cache: same is shared.</p></div>`;
    document.body.append(root);
    const paragraph = root.querySelectorAll("p")[1];
    const node = paragraph.firstChild!;
    const range = document.createRange();
    const start = node.textContent!.lastIndexOf("same");
    range.setStart(node, start);
    range.setEnd(node, start + 4);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const target = resolveAnnotationSelection(selection)!;
    expect(target.text).toBe("same");
    expect(target.messageId).toBe("a1");
    expect(target).not.toHaveProperty("contextBefore");
    expect(target).not.toHaveProperty("contextAfter");
    paragraph.textContent = "replacement";
    expect(target.text).toBe("same");
    selection.removeAllRanges();
    root.remove();
  });

  test("ignores neighboring paragraphs while still rejecting selections across tools", () => {
    const root = document.createElement("div");
    root.dataset.role = "assistant";
    root.dataset.messageId = "a1";
    root.innerHTML = `<div data-slot="aui_assistant-message-content"><p>${"b".repeat(250)}</p><div class="aui-tool-group-root">secret tool result</div><p>quote</p><p>${"a".repeat(250)}</p></div>`;
    document.body.append(root);
    const node = root.querySelectorAll("p")[1].firstChild!;
    const range = document.createRange();
    range.selectNodeContents(node);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const target = resolveAnnotationSelection(selection)!;
    expect(target.text).toBe("quote");
    expect(target).not.toHaveProperty("contextBefore");
    expect(target).not.toHaveProperty("contextAfter");
    // Crossing an excluded card is invalid even with valid endpoints.
    range.setStart(root.querySelectorAll("p")[0].firstChild!, 0);
    range.setEnd(node, 5);
    selection.removeAllRanges();
    selection.addRange(range);
    expect(resolveAnnotationSelection(selection)).toBeNull();
    selection.removeAllRanges();
    root.remove();
  });
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
      getRangeAt: () => {
        const range = document.createRange();
        range.setStart(anchorNode, 0);
        range.setEnd(focusNode, focusNode.textContent?.length ?? 0);
        return range;
      },
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

describe("MessageAnnotationCards", () => {
  test("renders nothing without annotations", () => {
    const { container } = render(
      <MessageAnnotationCards annotations={undefined} />
    );
    expect(container.firstChild).toBeNull();
  });

  test("shows a collapsed badge first and reveals cards on click", () => {
    const { container } = render(
      <MessageAnnotationCards
        annotations={[
          {
            quoted_text: "first quote",
            comment: "first note",
            source_excerpt: "intro",
          },
          { quoted_text: "second quote", comment: null, source_excerpt: null },
        ]}
      />
    );

    const badge = screen.getByRole("button", {
      name: "chat.annotation.chipLabel",
    });
    expect(badge.getAttribute("aria-expanded")).toBe("false");
    expect(
      container.querySelectorAll("[data-slot='aui_message-annotation-card']")
    ).toHaveLength(0);

    fireEvent.click(badge);

    expect(badge.getAttribute("aria-expanded")).toBe("true");
    const cards = container.querySelectorAll(
      "[data-slot='aui_message-annotation-card']"
    );
    expect(cards).toHaveLength(2);
    expect(screen.getByText("first quote")).toBeTruthy();
    expect(screen.getByText(/first note/)).toBeTruthy();
    expect(screen.getByText(/chat.annotation.cardSourceLabel/)).toBeTruthy();
    expect(screen.getByText("second quote")).toBeTruthy();
  });

  test("drops invalid entries instead of rendering broken cards", () => {
    const { container } = render(
      <MessageAnnotationCards
        annotations={[{ quoted_text: "   " }, { quoted_text: "valid" }]}
      />
    );

    fireEvent.click(
      screen.getByRole("button", { name: "chat.annotation.chipLabel" })
    );

    expect(
      container.querySelectorAll("[data-slot='aui_message-annotation-card']")
    ).toHaveLength(1);
    expect(screen.getByText("valid")).toBeTruthy();
  });
});
