// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationShare } from "@/app/newchat/assistant-ui/use-conversation-share";
import { useConversationShareRequest } from "@/stores/conversationShare";

const mocks = vi.hoisted(() => ({
  getDetail: vi.fn(),
  createShare: vi.fn(),
  config: vi.fn(),
  copy: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
  translation: {
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en", language: "en" },
  },
}));
vi.mock("react-i18next", () => ({ useTranslation: () => mocks.translation }));
vi.mock("antd", () => ({
  message: { error: mocks.error, success: mocks.success },
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: mocks,
}));
vi.mock("@/services/configService", () => ({
  configService: { fetchRuntimeFrontendConfig: mocks.config },
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
const options = {
  conversationId: 42,
  threadId: "thread-42",
  messages,
  isRunning: false,
  isLoading: false,
  readOnly: false,
};
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

beforeEach(() => {
  vi.clearAllMocks();
  useConversationShareRequest.getState().setRequest(null);
  mocks.createShare.mockResolvedValue({ share_id: "public-token" });
  mocks.config.mockResolvedValue({
    shareBaseUrl: "https://share.example/base/",
  });
  mocks.copy.mockResolvedValue(undefined);
});

it("defaults history to all visible turns and the answer entry to only its owning turn", async () => {
  const { result } = renderHook(() => useConversationShare(options));
  await act(() => result.current.enterShareMode());
  expect([...result.current.selectedShareMessageIds]).toEqual([11, 21]);
  await act(() => result.current.enterShareMode("12"));
  expect([...result.current.selectedShareMessageIds]).toEqual([11]);
  await act(() => result.current.createShare());
  expect(mocks.createShare).toHaveBeenCalledExactlyOnceWith({
    conversationId: 42,
    mode: "selected",
    selected_user_message_ids: [11],
    render_version: "newchat",
  });
  expect(mocks.copy).toHaveBeenCalledWith(
    "https://share.example/base/en/share/public-token"
  );
  expect(result.current.isShareMode).toBe(false);
});

it("toggles all and individual turns and refuses empty selection", async () => {
  const { result } = renderHook(() => useConversationShare(options));
  await act(() => result.current.enterShareMode());
  act(() => result.current.toggleShareAll());
  await act(() => result.current.createShare());
  expect(mocks.createShare).not.toHaveBeenCalled();
  act(() => result.current.toggleShareAll());
  act(() => result.current.toggleShareMessage(11));
  expect([...result.current.selectedShareMessageIds]).toEqual([21]);
});

it.each(["isRunning", "isLoading", "readOnly"] as const)(
  "refuses sharing while %s",
  async (flag) => {
    const { result } = renderHook(() =>
      useConversationShare({ ...options, [flag]: true })
    );
    await act(() => result.current.enterShareMode());
    expect(result.current.isShareMode).toBe(false);
    expect(mocks.getDetail).not.toHaveBeenCalled();
  }
);

it("resolves fresh runtime IDs while collapsing persisted refresh duplicates", async () => {
  const user = { role: "user", message: "question", message_index: 0 };
  mocks.getDetail.mockResolvedValue({
    data: [
      {
        message: [
          { ...user, message_id: 101 },
          { role: "assistant", message_id: 102 },
          { ...user, message_id: 103 },
        ],
      },
    ],
  });
  const { result } = renderHook(() =>
    useConversationShare({
      ...options,
      messages: [row("local-user", "user"), row("local-answer", "assistant")],
    })
  );
  await act(() => result.current.enterShareMode("local-answer"));
  expect([...result.current.selectedShareMessageIds]).toEqual([101]);
});

it.each([
  { backend: [] },
  { backend: [{ role: "user", message_id: -1 }] },
  {
    backend: [
      { role: "user", message_id: 11, message_index: 0 },
      { role: "user", message_id: 21, message_index: 2 },
    ],
  },
])(
  "fails closed for missing, invalid or ambiguous identities: %j",
  async ({ backend }) => {
    mocks.getDetail.mockResolvedValue({ data: [{ message: backend }] });
    const { result } = renderHook(() =>
      useConversationShare({ ...options, messages: [row("local", "user")] })
    );
    await act(() => result.current.enterShareMode());
    expect(result.current.isShareMode).toBe(false);
    expect(mocks.error).toHaveBeenCalled();
    expect(mocks.createShare).not.toHaveBeenCalled();
  }
);

it("leaves selection available after create failure and preserves the link when copying fails", async () => {
  const { result } = renderHook(() => useConversationShare(options));
  await act(() => result.current.enterShareMode("22"));
  mocks.createShare.mockRejectedValueOnce(new Error("offline"));
  await act(() => result.current.createShare());
  expect(result.current.isShareMode).toBe(true);
  expect([...result.current.selectedShareMessageIds]).toEqual([21]);
  mocks.copy.mockRejectedValueOnce(new Error("permission"));
  await act(() => result.current.createShare());
  expect(result.current.manualShareUrl).toBe(
    "https://share.example/base/en/share/public-token"
  );
  expect(result.current.isShareMode).toBe(false);
});

it("discards late identity resolution after the conversation changes", async () => {
  const detail = deferred<unknown>();
  mocks.getDetail.mockReturnValue(detail.promise);
  const { result, rerender } = renderHook(
    (id) =>
      useConversationShare({
        ...options,
        conversationId: id,
        messages: [row("local", "user")],
      }),
    { initialProps: 42 }
  );
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.enterShareMode();
  });
  rerender(43);
  await act(async () => {
    detail.resolve({
      data: [{ message: [{ role: "user", message_id: 101 }] }],
    });
    await pending;
  });
  expect(result.current.isShareMode).toBe(false);
  expect(result.current.selectedShareMessageIds.size).toBe(0);
});

it("waits for the requested history thread to load before consuming its request", async () => {
  const { result, rerender } = renderHook(
    (loading) => useConversationShare({ ...options, isLoading: loading }),
    { initialProps: true }
  );
  act(() =>
    useConversationShareRequest
      .getState()
      .setRequest({ conversationId: 42, threadId: "thread-42" })
  );
  expect(result.current.isShareMode).toBe(false);
  rerender(false);
  await waitFor(() => expect(result.current.isShareMode).toBe(true));
  expect([...result.current.selectedShareMessageIds]).toEqual([11, 21]);
  expect(useConversationShareRequest.getState().request).toBeNull();
});

it("cancels an open selection on navigation and suppresses late link copying", async () => {
  const created = deferred<{ share_id: string }>();
  mocks.createShare.mockReturnValue(created.promise);
  const { result, rerender } = renderHook(
    (id) => useConversationShare({ ...options, conversationId: id }),
    { initialProps: 42 }
  );
  await act(() => result.current.enterShareMode());
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.createShare();
  });
  rerender(43);
  await act(async () => {
    created.resolve({ share_id: "stale" });
    await pending;
  });
  expect(result.current.isShareMode).toBe(false);
  expect(mocks.copy).not.toHaveBeenCalled();
});

it("prevents duplicate create requests", async () => {
  const created = deferred<{ share_id: string }>();
  mocks.createShare.mockReturnValue(created.promise);
  const { result } = renderHook(() => useConversationShare(options));
  await act(() => result.current.enterShareMode());
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.createShare();
  });
  await act(() => result.current.createShare());
  expect(mocks.createShare).toHaveBeenCalledTimes(1);
  await act(async () => {
    created.resolve({ share_id: "one" });
    await pending;
  });
});

it("reports history loading failure and permits another attempt", async () => {
  mocks.getDetail.mockRejectedValueOnce(new Error("offline"));
  const { result } = renderHook(() =>
    useConversationShare({ ...options, messages: [row("local", "user")] })
  );
  await act(() => result.current.enterShareMode());
  expect(mocks.error).toHaveBeenCalledWith("chatInterface.shareCreateFailed");
  expect(result.current.disabled).toBe(false);
  mocks.getDetail.mockResolvedValueOnce({
    data: [{ message: [{ role: "user", message_id: 101 }] }],
  });
  await act(() => result.current.enterShareMode());
  expect([...result.current.selectedShareMessageIds]).toEqual([101]);
});

it("rejects an absent answer and an unsaved conversation", async () => {
  const { result } = renderHook(() => useConversationShare(options));
  await act(() => result.current.enterShareMode("missing-answer"));
  expect(result.current.isShareMode).toBe(false);
  const unsaved = renderHook(() =>
    useConversationShare({ ...options, conversationId: undefined })
  );
  await act(() => unsaved.result.current.enterShareMode());
  expect(unsaved.result.current.isShareMode).toBe(false);
  expect(mocks.createShare).not.toHaveBeenCalled();
});
