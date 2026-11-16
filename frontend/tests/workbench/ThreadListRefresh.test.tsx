// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type AssistantRuntime,
  type RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";
import { expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  BatchSelectionProvider,
  ThreadList,
} from "@/app/newchat/assistant-ui/thread-list";

vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({ availableMainAgents: [] }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));

type Page = Awaited<ReturnType<RemoteThreadListAdapter["list"]>>;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
const rows: Page = {
  threads: ["1", "2"].map((id) => ({
    remoteId: id,
    status: "regular" as const,
    title: `History ${id}`,
  })),
  nextCursor: "next-page",
};
const model = {
  async *run() {
    yield { content: [{ type: "text" as const, text: "Controlled response" }] };
  },
};
function setup() {
  let runtime!: AssistantRuntime;
  const first = deferred<Page>();
  const list = vi.fn<() => Promise<Page>>().mockReturnValue(first.promise);
  const adapter: RemoteThreadListAdapter = {
    list,
    async fetch(id) {
      return rows.threads.find((item) => item.remoteId === id)!;
    },
    async initialize() {
      return { remoteId: "draft" };
    },
    async rename() {},
    async archive() {},
    async unarchive() {},
    async delete() {},
    async generateTitle() {
      return createAssistantStream(() => {});
    },
  };
  function useControlledRuntime() {
    return useLocalRuntime(model);
  }
  function Harness({ source }: { source: RemoteThreadListAdapter }) {
    runtime = useRemoteThreadListRuntime({
      runtimeHook: useControlledRuntime,
      adapter: source,
    });
    return (
      <AssistantRuntimeProvider runtime={runtime}>
        <TooltipProvider>
          <BatchSelectionProvider>
            <div
              data-testid="history-viewport"
              style={{ height: 80, overflow: "auto" }}
            >
              <ThreadList />
            </div>
          </BatchSelectionProvider>
        </TooltipProvider>
      </AssistantRuntimeProvider>
    );
  }
  const query = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const tree = (source = adapter, scope = "owner") => (
    <QueryClientProvider client={query}>
      <Harness key={scope} source={source} />
    </QueryClientProvider>
  );
  const view = render(tree());
  const skeletons = () =>
    view.container.querySelectorAll('[data-slot="aui_thread-list-skeleton"]');
  return {
    ...view,
    first,
    list,
    adapter,
    tree,
    skeletons,
    runtime: () => runtime,
    close: () => {
      view.unmount();
      query.clear();
    },
  };
}

it("shows skeletons only before saved history arrives and then shows a confirmed empty state", async () => {
  const view = setup();
  try {
    await waitFor(() => expect(view.skeletons()).toHaveLength(5));
    await act(async () => view.first.resolve({ threads: [] }));
    await waitFor(() => expect(view.skeletons()).toHaveLength(0));
    expect(
      view.container.querySelector('[data-slot="aui_thread-list-item"]')
    ).toBeNull();
  } finally {
    view.close();
  }
});

it.each(["success", "failure"])(
  "keeps mounted rows, focus, scroll and active draft throughout a delayed %s refresh",
  async (outcome) => {
    const view = setup();
    try {
      await act(async () => view.first.resolve(rows));
      const unchanged = await screen.findByText("History 2");
      const original = screen.getByText("History 1");
      const activeId = Object.values(
        view.runtime().threads.getState().threadItems
      ).find((item) => item.remoteId === "1")!.id;
      await act(async () => view.runtime().threads.switchToThread(activeId));
      act(() =>
        view.runtime().thread.composer.setText("Keep this unsent draft")
      );
      const viewport = screen.getByTestId("history-viewport");
      viewport.scrollTop = 60;
      const trigger = original.closest("button")!;
      trigger.focus();
      const more = screen.getByRole("button", {
        name: "chat.threadList.loadMore",
      });
      const next = deferred<Page>();
      view.list.mockReturnValue(next.promise);
      let refresh!: Promise<void>;
      act(() => {
        refresh = view.runtime().threads.reload();
      });
      await waitFor(() =>
        expect(view.runtime().threads.getState().isLoading).toBe(true)
      );
      expect(view.skeletons()).toHaveLength(0);
      expect(original.isConnected).toBe(true);
      expect(unchanged.isConnected).toBe(true);
      expect(document.activeElement).toBe(trigger);
      expect(viewport.scrollTop).toBe(60);
      expect(more.isConnected).toBe(true);
      expect(more).toBeDisabled();
      if (outcome === "success") {
        await act(async () => {
          next.resolve({
            ...rows,
            threads: [
              { ...rows.threads[0], title: "Updated history" },
              rows.threads[1],
            ],
          });
          await refresh;
        });
        expect(await screen.findByText("Updated history")).toBe(original);
      } else {
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        try {
          await act(async () => {
            next.reject(new Error("Controlled offline refresh"));
            await refresh;
          });
          expect(screen.getByText("History 1")).toBe(original);
        } finally {
          error.mockRestore();
        }
      }
      expect(screen.getByText("History 2")).toBe(unchanged);
      expect(view.skeletons()).toHaveLength(0);
      expect(viewport.scrollTop).toBe(60);
      expect(document.activeElement).toBe(trigger);
      expect(view.runtime().threads.getState().mainThreadId).toBe(activeId);
      expect(view.runtime().thread.composer.getState().text).toBe(
        "Keep this unsent draft"
      );
    } finally {
      view.close();
    }
  }
);

it("removes confirmed deleted history and does not retain another owner's rows", async () => {
  const view = setup();
  try {
    await act(async () => view.first.resolve(rows));
    await screen.findByText("History 1");
    view.list.mockResolvedValue({ threads: [] });
    await act(async () => view.runtime().threads.reload());
    expect(screen.queryByText("History 1")).toBeNull();
    expect(view.skeletons()).toHaveLength(0);
    view.list.mockResolvedValue(rows);
    await act(async () => view.runtime().threads.reload());
    await screen.findByText("History 1");
    const next = deferred<Page>();
    view.rerender(
      view.tree({ ...view.adapter, list: () => next.promise }, "other-owner")
    );
    await waitFor(() => expect(view.skeletons()).toHaveLength(5));
    expect(screen.queryByText("History 1")).toBeNull();
    await act(async () => next.resolve({ threads: [] }));
  } finally {
    view.close();
  }
});
