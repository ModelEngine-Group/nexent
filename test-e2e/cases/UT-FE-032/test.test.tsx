// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getLocalFileDownloadUrl,
  getLocalFilePreviewUrl,
} from "@/services/storageService";
import { useConversationShare } from "@/app/newchat/assistant-ui/use-conversation-share";
import { ConversationShareContext } from "@/app/newchat/assistant-ui/conversation-share-context";
import { ConversationShareMenuItem } from "@/app/newchat/assistant-ui/conversation-share-menu-item";
import { ConversationShareFooter } from "@/app/newchat/assistant-ui/conversation-share-footer";
import { useConversationShareRequest } from "@/stores/conversationShare";

const mocks = vi.hoisted(() => ({
  createShare: vi.fn(),
  copy: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ message: { getState: () => ({ id: "22" }) } }),
  ActionBarMorePrimitive: {
    Item: ({
      onSelect,
      children,
      ...props
    }: {
      onSelect: () => void;
      children: React.ReactNode;
    }) => (
      <button {...props} onClick={onSelect}>
        {children}
      </button>
    ),
  },
}));
vi.mock("react-i18next", async (load) => {
  const translation = {
    t: (key: string, options?: { count: number }) =>
      options ? `${key}:${options.count}` : key,
    i18n: { resolvedLanguage: "zh" },
  };
  return { ...(await load<object>()), useTranslation: () => translation };
});
vi.mock("@/services/conversationService", () => ({
  conversationService: mocks,
}));
vi.mock("@/services/configService", () => ({
  configService: {
    fetchRuntimeFrontendConfig: async () => ({
      shareBaseUrl: "https://share.example",
    }),
  },
}));
vi.mock("@/lib/clipboard", () => ({ copyToClipboard: mocks.copy }));

const row = (id: string, role: "user" | "assistant") => ({
  id,
  role,
  content: [{ type: "text", text: id }],
});
const messages = [
  row("11", "user"),
  row("12", "assistant"),
  row("21", "user"),
  row("22", "assistant"),
];
function Harness({ running = false }: { running?: boolean }) {
  const share = useConversationShare({
    conversationId: 42,
    threadId: "saved",
    messages,
    isRunning: running,
    isLoading: false,
    readOnly: false,
  });
  return (
    <ConversationShareContext.Provider
      value={{ disabled: share.disabled, shareTurn: share.enterShareMode }}
    >
      {!share.isShareMode ? (
        <ConversationShareMenuItem />
      ) : (
        <>
          {[11, 21].map((id) => (
            <label key={id}>
              turn-{id}
              <input
                type="checkbox"
                checked={share.selectedShareMessageIds.has(id)}
                onChange={() => share.toggleShareMessage(id)}
              />
            </label>
          ))}
          <ConversationShareFooter
            selectedCount={share.selectedShareMessageIds.size}
            totalCount={2}
            creating={share.isCreatingShare}
            onToggleAll={share.toggleShareAll}
            onCancel={share.leaveShareMode}
            onCreate={share.createShare}
          />
        </>
      )}
      {share.manualShareUrl && (
        <input
          aria-label="generated link"
          readOnly
          value={share.manualShareUrl}
        />
      )}
    </ConversationShareContext.Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useConversationShareRequest.getState().setRequest(null);
  mocks.createShare.mockResolvedValue({ share_id: "snapshot" });
  mocks.copy.mockResolvedValue(undefined);
});
afterEach(() => useConversationShareRequest.getState().setRequest(null));

describe("UT-FE-032", () => {
  it("UT-FE-032 builds preview/download URLs without mixing operations", () => {
    const preview = getLocalFilePreviewUrl(
      "s3://bucket/path/file.txt",
      "file.txt",
    );
    const download = getLocalFileDownloadUrl(
      "s3://bucket/path/file.txt",
      "file.txt",
    );
    expect(preview).not.toBe(download);
    expect(preview).toContain("preview");
  });
  it("UT-FE-032 answer menu selects its turn and creates only the selected snapshot", async () => {
    render(<Harness />);
    fireEvent.click(
      screen.getByRole("button", { name: "chatInterface.shareConversation" }),
    );
    await waitFor(() => expect(screen.getByLabelText("turn-21")).toBeChecked());
    expect(screen.getByLabelText("turn-11")).not.toBeChecked();
    expect(screen.getByText("chatInterface.selectedShareCount:1")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "chatInterface.createPublicLink" }),
    );
    await waitFor(() =>
      expect(mocks.createShare).toHaveBeenCalledExactlyOnceWith({
        conversationId: 42,
        mode: "selected",
        selected_user_message_ids: [21],
        render_version: "newchat",
      }),
    );
    await waitFor(() =>
      expect(mocks.copy).toHaveBeenCalledWith(
        "https://share.example/zh/share/snapshot",
      ),
    );
  });
  it("UT-FE-032 history request selects all, allows deselection and cancellation without publishing", async () => {
    render(<Harness />);
    act(() =>
      useConversationShareRequest
        .getState()
        .setRequest({ threadId: "saved", conversationId: 42 }),
    );
    await waitFor(() => expect(screen.getByLabelText("turn-11")).toBeChecked());
    expect(screen.getByLabelText("turn-21")).toBeChecked();
    fireEvent.click(screen.getByLabelText("common.selectAll"));
    expect(
      screen.getByRole("button", { name: "chatInterface.createPublicLink" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByLabelText("turn-11"));
    expect(screen.getByText("chatInterface.selectedShareCount:1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
    expect(mocks.createShare).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "chatInterface.shareConversation" }),
    ).toBeTruthy();
  });
  it("UT-FE-032 running conversations disable the share menu", () => {
    render(<Harness running />);
    expect(
      screen.getByRole("button", { name: "chatInterface.shareConversation" }),
    ).toBeDisabled();
  });
  it("UT-FE-032 clipboard denial retains the generated link for manual copying", async () => {
    mocks.copy.mockRejectedValueOnce(new Error("denied"));
    render(<Harness />);
    fireEvent.click(
      screen.getByRole("button", { name: "chatInterface.shareConversation" }),
    );
    await waitFor(() => expect(screen.getByLabelText("turn-21")).toBeChecked());
    fireEvent.click(
      screen.getByRole("button", { name: "chatInterface.createPublicLink" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("generated link")).toHaveValue(
        "https://share.example/zh/share/snapshot",
      ),
    );
    expect(mocks.createShare).toHaveBeenCalledTimes(1);
  });
});
