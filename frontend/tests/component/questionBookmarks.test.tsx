// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  render,
  renderHook,
  waitFor,
  fireEvent,
  screen,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { useQuestionBookmarks } from "@/hooks/chat/useQuestionBookmarks";
import { QuestionBookmarkRail } from "@/app/newchat/ui/question-bookmark-rail";
import { collectQuestionDirectory } from "@/app/newchat/utils/question-directory";

const state = vi.hoisted(() => ({
  user: { id: "user", tenantId: "tenant" },
  get: vi.fn(),
  set: vi.fn(),
  detail: vi.fn(),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: state.user }),
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: {
    getQuestionBookmarks: state.get,
    setQuestionBookmark: state.set,
    getDetail: state.detail,
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: { index?: number }) =>
      params?.index ? `${key}:${params.index}` : key,
  }),
}));

const clients: QueryClient[] = [];
function setup(initialId = 42) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return {
    client,
    ...renderHook(({ id, enabled }) => useQuestionBookmarks(id, enabled), {
      initialProps: { id: initialId, enabled: true },
      wrapper,
    }),
  };
}
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  vi.resetAllMocks();
  state.user = { id: "user", tenantId: "tenant" };
});

test("loads saved bookmarks and persists removal with explicit state", async () => {
  state.get.mockResolvedValue([17]);
  state.set.mockResolvedValue([]);
  const { result } = setup();
  await waitFor(() => expect(result.current.ready).toBe(true));
  expect(result.current.ids).toEqual([17]);
  act(() => {
    result.current.toggle(17, false);
    result.current.toggle(17, false);
  });
  await waitFor(() => expect(result.current.ids).toEqual([]));
  expect(state.set).toHaveBeenCalledWith(42, 17, false);
  expect(state.set).toHaveBeenCalledTimes(1);
});

test("failed saves retain known server state; pending saves cannot be repeated", async () => {
  state.get.mockResolvedValue([17]);
  let reject!: (error: Error) => void;
  state.set.mockImplementation(
    () =>
      new Promise((_, failure) => {
        reject = failure;
      })
  );
  const { result } = setup();
  await waitFor(() => expect(result.current.ready).toBe(true));
  act(() => result.current.toggle(17, false));
  await waitFor(() => expect(result.current.pending).toBe(true));
  act(() => result.current.toggle(17, false));
  expect(state.set).toHaveBeenCalledTimes(1);
  act(() => reject(new Error("offline")));
  await waitFor(() => expect(result.current.failed).toBe(true));
  expect(result.current.ids).toEqual([17]);
});

test("a late write stays in the original account and conversation cache", async () => {
  state.get.mockResolvedValue([]);
  let finish!: (ids: number[]) => void;
  state.set.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const { result, rerender, client } = setup();
  await waitFor(() => expect(result.current.ready).toBe(true));
  act(() => result.current.toggle(17, true));
  await waitFor(() => expect(result.current.pending).toBe(true));
  state.user = { id: "other", tenantId: "tenant" };
  rerender({ id: 43, enabled: true });
  await waitFor(() => expect(result.current.ready).toBe(true));
  act(() => finish([17]));
  await waitFor(() => expect(result.current.pending).toBe(false));
  expect(result.current.ids).toEqual([]);
  expect(
    client.getQueryData(["question-bookmarks", "user", "tenant", 42])
  ).toEqual([17]);
});

test("read-only and unsaved conversations do not fetch or mutate", async () => {
  const { result, rerender } = setup(0);
  act(() => result.current.toggle(17, true));
  rerender({ id: 42, enabled: false });
  act(() => result.current.toggle(17, true));
  expect(state.get).not.toHaveBeenCalled();
  expect(state.set).not.toHaveBeenCalled();
  expect(result.current.ready).toBe(false);
});

test("failed initial reads disable writes and can be retried", async () => {
  state.get.mockRejectedValueOnce(new Error("offline")).mockResolvedValue([17]);
  const { result } = setup();
  await waitFor(() => expect(result.current.failed).toBe(true));
  expect(result.current.ready).toBe(false);
  act(() => result.current.toggle(17, true));
  expect(state.set).not.toHaveBeenCalled();
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.ready).toBe(true));
  expect(result.current.ids).toEqual([17]);
});

test("newly generated runtime IDs resolve to persisted questions before bookmarking", async () => {
  state.get.mockResolvedValue([]);
  state.set.mockResolvedValue([17]);
  state.detail.mockResolvedValue({
    data: [
      {
        message: [
          { message_id: 17, message_index: 0, role: "user", message: "hello" },
        ],
      },
    ],
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const questions = collectQuestionDirectory([
    {
      id: "runtime-id",
      role: "user",
      content: [{ type: "text", text: "hello" }],
    },
  ]);
  render(
    <QueryClientProvider client={client}>
      <QuestionBookmarkRail
        conversationId={42}
        questions={questions}
        onJump={vi.fn()}
      />
    </QueryClientProvider>
  );
  fireEvent.focus(
    screen.getByRole("button", { name: "chat.questions.jump:1" })
  );
  const mark = await screen.findByRole("button", {
    name: "chat.questions.bookmark",
  });
  await waitFor(() => expect(mark).not.toBeDisabled());
  fireEvent.click(mark);
  await waitFor(() => expect(state.set).toHaveBeenCalledWith(42, 17, true));
  expect(
    await screen.findByRole("button", { name: "chat.questions.unbookmark" })
  ).toHaveAttribute("aria-pressed", "true");
});

test("ambiguous or mismatched runtime history cannot bookmark a different question", async () => {
  state.get.mockResolvedValue([]);
  state.detail.mockResolvedValue({
    data: [
      {
        message: [
          { message_id: 99, role: "user", message: "another question" },
        ],
      },
    ],
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <QuestionBookmarkRail
        conversationId={42}
        questions={collectQuestionDirectory([
          {
            id: "runtime-id",
            role: "user",
            content: [{ type: "text", text: "hello" }],
          },
        ])}
        onJump={vi.fn()}
      />
    </QueryClientProvider>
  );
  fireEvent.focus(
    screen.getByRole("button", { name: "chat.questions.jump:1" })
  );
  const mark = await screen.findByRole("button", {
    name: "chat.questions.bookmark",
  });
  await waitFor(() => expect(state.detail).toHaveBeenCalledWith(42));
  expect(mark).toBeDisabled();
  fireEvent.click(mark);
  expect(state.set).not.toHaveBeenCalled();
});
