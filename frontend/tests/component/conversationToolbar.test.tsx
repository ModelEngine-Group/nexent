// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ConversationToolbar } from "@/app/newchat/assistant-ui/conversation-toolbar";
import { ConversationArtifactsEntryProvider } from "@/app/newchat/ui/conversation-artifacts-context";
import { copyToClipboard } from "@/lib/clipboard";
import en from "@/public/locales/en/common.json";
import zh from "@/public/locales/zh/common.json";

const locale = vi.hoisted(() => ({ current: "en" }));
const translations: Record<string, Record<string, unknown>> = { en, zh };
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { id?: string; count?: number }) => {
      const value = translations[locale.current][key];
      return (typeof value === "string" ? value : key)
        .replace("{{id}}", values?.id ?? "")
        .replace("{{count}}", String(values?.count ?? ""));
    },
  }),
}));
vi.mock("@/lib/clipboard", () => ({ copyToClipboard: vi.fn() }));

const copy = vi.mocked(copyToClipboard);

it.each([undefined, 0, -1, 10.5, NaN, Number.MAX_SAFE_INTEGER + 1])(
  "does not expose an unsaved or invalid conversation ID: %s",
  (conversationId) => {
    const { container } = render(
      <ConversationToolbar conversationId={conversationId} />
    );
    expect(container.firstChild).toBeNull();
  }
);

it("displays and copies only the current saved ID without affecting artifacts", async () => {
  locale.current = "en";
  copy.mockResolvedValue(undefined);
  const open = vi.fn();
  const view = (conversationId?: number) => (
    <App>
      <ConversationArtifactsEntryProvider count={1} open={open}>
        <ConversationToolbar conversationId={conversationId} />
      </ConversationArtifactsEntryProvider>
    </App>
  );
  const { rerender } = render(view());
  expect(
    screen.queryByRole("button", { name: /Copy conversation ID/ })
  ).toBeNull();

  rerender(view(42));
  const first = screen.getByRole("button", { name: "Copy conversation ID 42" });
  expect(first).toHaveTextContent("Conversation ID: 42");
  fireEvent.click(first);
  expect(await screen.findByText("Conversation ID copied")).toBeVisible();
  expect(copy).toHaveBeenLastCalledWith("42");

  rerender(view(43));
  expect(
    screen.queryByRole("button", { name: "Copy conversation ID 42" })
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Copy conversation ID 43" })
  );
  fireEvent.click(
    screen.getByRole("button", { name: "View all artifacts (1)" })
  );
  expect(copy).toHaveBeenLastCalledWith("43");
  expect(open).toHaveBeenCalledOnce();
});

it("shows a localized failure message and leaves the ID visible", async () => {
  locale.current = "zh";
  copy.mockRejectedValueOnce(new Error("Clipboard unavailable"));
  render(
    <App>
      <ConversationToolbar conversationId={77} />
    </App>
  );
  const button = screen.getByRole("button", { name: "复制会话 ID 77" });
  fireEvent.click(button);
  expect(await screen.findByText("复制会话 ID 失败")).toBeVisible();
  expect(button).toHaveTextContent("会话 ID: 77");
  expect(copy).toHaveBeenCalledExactlyOnceWith("77");
});
