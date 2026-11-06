// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, waitFor } from "@testing-library/react";
import { StrictMode, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuiState, type AssistantRuntime } from "@assistant-ui/react";
import { expect, it, vi } from "vitest";
import {
  WorkbenchSessionProvider,
  useWorkbenchSession,
} from "@/features/workbench/providers/WorkbenchSessionProvider";
import { conversationService } from "@/services/conversationService";
import { initialWorkbenchState } from "@/features/workbench/state";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useParams: () => ({ locale: "zh" }),
}));
vi.mock("@/features/workbench/api", () => ({
  fetchWorkbenchBootstrap: async () => ({ modes: {} }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { id: "user", tenantId: "tenant" } }),
}));
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({ agents: [], isLoading: false }),
}));
vi.mock("@/hooks/useConfig", () => ({ useConfig: () => ({}) }));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  planRegistry: { data: null },
  remoteChatModelAdapter: { async *run() {} },
}));
vi.mock("@/app/newchat/adapter/attachment-adapter", () => ({
  createNewChatAttachmentAdapter: () => undefined,
}));

it("shares route, real thread metadata/history, page and late resume reads across activation and remount", async () => {
  const config = {
    ...initialWorkbenchState.config,
    model_id: 17,
    generation_config: {
      deep_thinking: false,
      temperature: 0.6,
      top_p: 0.8,
      requested_output_tokens: 2048,
    },
  };
  const get = vi
    .spyOn(conversationService, "getById")
    .mockImplementation(async (id) => ({
      conversation_id: Number(id),
      conversation_title: `Saved ${id}`,
      create_time: 0,
      message: [],
      workbench_config: config,
      workbench_config_version: 8,
      runtime_metadata: { key: id },
      runtime_metadata_version: 4,
    }));
  const legacyHistory = vi.spyOn(conversationService, "getDetail");
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [42, 43].map((id) => ({
      conversation_id: id,
      conversation_title: `Saved ${id}`,
      create_time: 0,
      update_time: 0,
    })),
    metadata: { total: 2, today: 0, last_7_days: 0, older: 2 },
  });
  vi.spyOn(conversationService, "getWorkbenchPins").mockResolvedValue({
    items: [],
  });
  let runtime!: AssistantRuntime;
  const restored: unknown[] = [];
  function Consumers() {
    const session = useWorkbenchSession();
    runtime = session.runtime;
    const id = useAuiState(
      (s) =>
        s.threads.threadItems.find((item) => item.id === s.threads.mainThreadId)
          ?.remoteId
    );
    useEffect(() => {
      if (!id || !/^\d+$/.test(id)) return;
      let cancelled = false;
      void session.conversationDetails.load(id).then(async (first) => {
        // Model the metadata/resume stages that run after history has settled.
        const later = await session.conversationDetails.load(id);
        if (!cancelled)
          restored.push({
            id,
            config: first.workbench_config,
            metadata: later.runtime_metadata,
            version: later.runtime_metadata_version,
          });
      });
      return () => {
        cancelled = true;
      };
    }, [id, session.conversationDetails]);
    return null;
  }
  const client = new QueryClient();
  const mount = () =>
    render(
      <QueryClientProvider client={client}>
        <StrictMode>
          <WorkbenchSessionProvider>
            <Consumers />
          </WorkbenchSessionProvider>
        </StrictMode>
      </QueryClientProvider>
    );
  window.history.replaceState({}, "", "/zh/workbench?conversation_id=42");
  const first = mount();
  await waitFor(() => expect(restored).toHaveLength(1));
  expect(get).toHaveBeenCalledExactlyOnceWith("42");
  await act(async () => {
    await runtime.threads.switchToThread("43");
  });
  await waitFor(() => expect(restored).toHaveLength(2));
  await act(async () => {
    await runtime.threads.switchToThread("42");
  });
  await waitFor(() => expect(restored).toHaveLength(3));
  expect(get.mock.calls.map(([id]) => id)).toEqual(["42", "43", "42"]);
  await act(async () => {
    await runtime.threads.switchToThread("42");
  });
  expect(get).toHaveBeenCalledTimes(3);
  expect(restored[2]).toEqual({
    id: "42",
    config,
    metadata: { key: "42" },
    version: 4,
  });
  expect(legacyHistory).not.toHaveBeenCalled();
  first.unmount();
  const second = mount();
  await waitFor(() => expect(restored).toHaveLength(4));
  expect(get).toHaveBeenCalledTimes(4);
  expect(router.replace).not.toHaveBeenCalled();
  second.unmount();
  client.clear();
});
