// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  WorkbenchSessionProvider,
  useWorkbenchSession,
} from "@/features/workbench/providers/WorkbenchSessionProvider";
import { WorkbenchLoadingBoundary } from "@/features/workbench/components/WorkbenchLoadingBoundary";
import { getWorkbenchSendability } from "@/features/workbench/state";
import type { WorkbenchBootstrap } from "@/features/workbench/types";

const mocks = vi.hoisted(() => ({ bootstrap: vi.fn(), logError: vi.fn() }));
vi.mock("@/features/workbench/api", () => ({
  fetchWorkbenchBootstrap: mocks.bootstrap,
}));
vi.mock("@/services/conversationService", () => ({ conversationService: {} }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({}) }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: undefined }),
}));
vi.mock("@assistant-ui/react", () => ({
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => children,
  useRemoteThreadListRuntime: () => ({}),
  useLocalRuntime: vi.fn(),
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: {},
}));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({
  createConversationThreadListAdapter: () => ({}),
}));
vi.mock("@/app/newchat/assistant-ui/thread-pins", () => ({
  getWorkbenchPinStorageKey: vi.fn(),
}));
vi.mock("@/app/newchat/adapter/attachment-adapter", () => ({
  createNewChatAttachmentAdapter: vi.fn(),
}));
vi.mock("@/app/newchat/adapter/server-dictation-adapter", () => ({
  ServerDictationAdapter: class {},
}));
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({ isLoading: false, agents: [] }),
}));
vi.mock("@/hooks/useConfig", () => ({ useConfig: () => ({}) }));
vi.mock("@/features/workbench/hooks/useConversationRouteGuard", () => ({
  useConversationRouteGuard: vi.fn(),
}));
vi.mock("@/lib/logger", () => ({ default: { error: mocks.logError } }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: () => "加载中" }),
}));

function Workbench() {
  const session = useWorkbenchSession();
  const { reason } = getWorkbenchSendability(
    session.workbenchState,
    session.workbenchBootstrap ?? undefined
  );
  return (
    <WorkbenchLoadingBoundary
      conversationReady
      modelsLoading={false}
      bootstrapLoading={session.isLoadingWorkbenchBootstrap}
      resourcesResolving={session.workbenchState.resolving}
    >
      <textarea aria-label="输入消息" />
      {reason && <p role="alert">{reason}</p>}
    </WorkbenchLoadingBoundary>
  );
}

it.each(["enabled", "disabled", "rejected"])(
  "hides premature capability warnings and ends loading when bootstrap is %s",
  async (outcome) => {
    let resolve!: (value: WorkbenchBootstrap) => void;
    let reject!: (reason: Error) => void;
    mocks.bootstrap.mockReturnValueOnce(
      new Promise<WorkbenchBootstrap>((yes, no) => {
        resolve = yes;
        reject = no;
      })
    );
    render(
      <WorkbenchSessionProvider>
        <Workbench />
      </WorkbenchSessionProvider>
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await act(async () => {
      if (outcome === "rejected") reject(new Error("capability load failed"));
      else
        resolve({
          schema_version: 3,
          modes: {
            generic_chat: { enabled: outcome === "enabled" },
            single_agent_chat: { enabled: true },
            multi_agent_chat: { enabled: false },
            agent_create: { enabled: true },
            skill_create: { enabled: true },
          },
        });
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    if (outcome === "enabled")
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    else expect(screen.getByRole("alert")).toHaveTextContent("通用对话服务");
    if (outcome === "rejected") expect(mocks.logError).toHaveBeenCalled();
  }
);
