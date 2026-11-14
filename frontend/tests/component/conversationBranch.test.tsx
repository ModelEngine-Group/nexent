// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  computeBranchTurnIndex,
  type BranchMessageLike,
} from "@/app/newchat/utils/conversation-branch";
import { ConversationBranchMenuItem } from "@/app/newchat/assistant-ui/conversation-branch-menu-item";
import { ConversationBranchContext } from "@/app/newchat/assistant-ui/conversation-branch-context";

const auiMocks = vi.hoisted(() => ({
  getState: vi.fn(() => ({ id: "assistant-2", branchNumber: 2 })),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ message: { getState: auiMocks.getState } }),
  ActionBarMorePrimitive: {
    Item: ({
      onSelect,
      disabled,
      children,
    }: {
      onSelect?: () => void;
      disabled?: boolean;
      children: React.ReactNode;
    }) => (
      <button
        type="button"
        data-testid="branch-item"
        disabled={disabled}
        onClick={onSelect}
      >
        {children}
      </button>
    ),
  },
}));

const makeMessage = (id: string, role: string): BranchMessageLike => ({
  id,
  role,
});

const renderMenuItem = (
  contextValue: {
    disabled: boolean;
    branchFromMessage: (
      assistantMessageId: string,
      answerIndex: number
    ) => void;
  } | null
) =>
  render(
    contextValue ? (
      <ConversationBranchContext.Provider value={contextValue}>
        <ConversationBranchMenuItem />
      </ConversationBranchContext.Provider>
    ) : (
      <ConversationBranchMenuItem />
    )
  );

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  document.body.innerHTML = "";
});

test("computeBranchTurnIndex counts turns up to the selected answer", () => {
  const messages = [
    makeMessage("u1", "user"),
    makeMessage("a1", "assistant"),
    makeMessage("u2", "user"),
    makeMessage("a2", "assistant"),
    makeMessage("u3", "user"),
    makeMessage("a3", "assistant"),
  ];

  expect(computeBranchTurnIndex(messages, "a1")).toBe(1);
  expect(computeBranchTurnIndex(messages, "a2")).toBe(2);
  expect(computeBranchTurnIndex(messages, "a3")).toBe(3);
});

test("computeBranchTurnIndex ignores non-user rows while keeping turn order", () => {
  const messages = [
    makeMessage("s1", "system"),
    makeMessage("u1", "user"),
    makeMessage("s2", "system"),
    makeMessage("a1", "assistant"),
  ];

  expect(computeBranchTurnIndex(messages, "a1")).toBe(1);
});

test("computeBranchTurnIndex returns null for unknown ids or missing questions", () => {
  const messages = [makeMessage("u1", "user"), makeMessage("a1", "assistant")];

  expect(computeBranchTurnIndex(messages, "missing")).toBeNull();
  expect(computeBranchTurnIndex([], "a1")).toBeNull();
  expect(
    computeBranchTurnIndex([makeMessage("a0", "assistant")], "a0")
  ).toBeNull();
});

test("menu item invokes the branch handler with the aui message id", () => {
  const branchFromMessage = vi.fn();

  renderMenuItem({ disabled: false, branchFromMessage });
  fireEvent.click(screen.getByTestId("branch-item"));

  expect(branchFromMessage).toHaveBeenCalledTimes(1);
  expect(branchFromMessage).toHaveBeenCalledWith("assistant-2", 2);
});

test("menu item reads the selected answer version at click time", () => {
  const branchFromMessage = vi.fn();
  renderMenuItem({ disabled: false, branchFromMessage });
  auiMocks.getState.mockReturnValueOnce({ id: "123", branchNumber: 1 });
  fireEvent.click(screen.getByTestId("branch-item"));
  expect(branchFromMessage).toHaveBeenCalledWith("123", 1);
});

test("menu item surfaces the localized branch label", () => {
  renderMenuItem({ disabled: false, branchFromMessage: vi.fn() });

  expect(screen.getByText("chat.thread.branchToNewChat")).toBeTruthy();
});

test("menu item is disabled when branching is unavailable", () => {
  renderMenuItem({ disabled: true, branchFromMessage: vi.fn() });

  const item = screen.getByTestId("branch-item") as HTMLButtonElement;
  expect(item.disabled).toBe(true);
});

test("menu item renders nothing without the branch context", () => {
  renderMenuItem(null);

  expect(screen.queryByTestId("branch-item")).toBeNull();
});
