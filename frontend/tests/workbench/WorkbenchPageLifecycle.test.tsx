// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen, waitFor } from "@testing-library/react";
import {
  useCallback,
  useReducer,
  useState,
  useLayoutEffect,
  type ComponentProps,
  type ReactNode,
} from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Chat } from "@/app/newchat/assistant-ui/chat";
import type { ConversationKnowledgeScope } from "@/types/knowledgeScope";
import type { ApiConversationDetail } from "@/types/conversation";
import {
  initialWorkbenchState,
  workbenchReducer,
} from "@/features/workbench/state";
import { searchAgentInfo } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import WorkbenchPage from "@/features/workbench/WorkbenchPage";
import { conversationService } from "@/services/conversationService";
import { QueryClient } from "@tanstack/react-query";
import { createConversationDetailLoader } from "@/lib/conversationDetails";

const view = vi.hoisted(() => ({
  threadId: "a" as string | undefined,
  items: [
    { id: "a", remoteId: "101" },
    { id: "b", remoteId: "202" },
  ],
  props: null as ComponentProps<typeof Chat> | null,
  setRunConfig: vi.fn(),
  restoreAgent: vi.fn(),
  markGenerationCompleted: vi.fn(),
  markCompletionSynced: vi.fn(),
  back: vi.fn(),
  nextThread: 0,
  bootstrap: null as {
    generic_agent: { agent_id: number; version_no: number };
  } | null,
  listLoading: false,
  threadLoading: false,
  running: false,
  initialConfigVersion: 7,
}));
const runtime = {
  thread: {
    getState: () => ({ isRunning: false }),
    composer: {
      setRunConfig: view.setRunConfig,
      getState: () => ({ text: "", attachments: [] }),
      setText: vi.fn(),
    },
  },
  threads: {
    getState: () => ({ mainThreadId: view.threadId }),
    switchToNewThread: vi.fn(async () => {
      view.threadId = `creation-${++view.nextThread}`;
    }),
    switchToThread: vi.fn(async (id: string) => {
      view.threadId = id;
    }),
  },
};
const config = {
  ...initialWorkbenchState.config,
  requested_output_tokens: 1234,
};
const translate = (_key: string, fallback?: unknown) =>
  typeof fallback === "string" ? fallback : _key;
vi.mock("@assistant-ui/react", () => ({
  useAuiState: (select: (state: unknown) => unknown) =>
    select({
      threads: {
        mainThreadId: view.threadId,
        isLoading: view.listLoading,
        threadItems: view.items,
      },
      thread: { isLoading: view.threadLoading, isRunning: view.running },
    }),
}));
vi.mock("@/features/workbench/providers/WorkbenchSessionProvider", () => ({
  WorkbenchSessionProvider: ({ children }: { children: ReactNode }) => children,
  useWorkbenchSession: () => {
    const [conversationDetails] = useState(() =>
      createConversationDetailLoader(new QueryClient(), "page-test")
    );
    const active = view.items.find(
      (item) => item.id === view.threadId
    )?.remoteId;
    useLayoutEffect(
      () => conversationDetails.activate(active),
      [conversationDetails, active]
    );
    const [state, dispatch] = useReducer(workbenchReducer, {
      ...initialWorkbenchState,
      config,
      configVersion: view.initialConfigVersion,
    });
    const changeMode = useCallback(
      (mode: "agent_create" | "skill_create" | "generic_chat") =>
        dispatch({ type: "select-mode", mode }),
      []
    );
    return {
      conversationDetails,
      runtime,
      selectedAgent: null,
      isLoadingAgents: false,
      agents: [],
      onRestoreAgent: view.restoreAgent,
      onBack: view.back,
      isDictationConfigured: false,
      workbenchState: state,
      workbenchBootstrap: view.bootstrap,
      onWorkbenchModeChange: changeMode,
      dispatchWorkbench: dispatch,
    };
  },
}));
vi.mock("@/app/newchat/assistant-ui/chat", () => ({
  Chat: (props: ComponentProps<typeof Chat>) => {
    view.props = props;
    return <input aria-label="workbench draft" defaultValue="Keep my draft" />;
  },
}));
vi.mock("@/app/newchat/assistant-ui/composer-tools", () => ({
  ComposerAttachment: () => null,
  ComposerDictation: () => null,
}));
vi.mock("@/app/newchat/assistant-ui/threadlist-sidebar", () => ({
  ThreadListSidebar: () => null,
}));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({
  cacheHistoricalChatMode: vi.fn(),
  generateConversationTitle: vi.fn(),
  restoreHistoricalChatMode: vi.fn(),
  restoreHistoricalPlan: vi.fn(),
  setHistoricalChatModeListener: vi.fn(),
  setServerConversationIdState: vi.fn(),
}));
vi.mock("@/features/workbench/hooks/useConversationResume", () => ({
  useConversationResume: vi.fn(),
}));
vi.mock("@/components/ui/sidebar", () => ({
  SidebarProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ llmModels: [], availableLlmModels: [], isLoading: false }),
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: undefined }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    hasPermission: () => true,
    user: { id: "u", tenantId: "t", email: "test@example.com" },
  }),
}));
vi.mock("@/contexts/nl2AgentFlow", () => {
  const noop = vi.fn();
  return {
    Nl2AgentFlowProvider: ({ children }: { children: ReactNode }) => children,
    useNl2AgentFlow: () => ({
      resetFlow: noop,
      markGenerationCompleted: view.markGenerationCompleted,
      markCompletionSynced: view.markCompletionSynced,
      markPromptGenerationFailed: noop,
      isComposerDisabled: false,
    }),
  };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate, i18n: { language: "zh" } }),
}));
vi.mock("@/app/i18n", () => ({ default: { t: (key: string) => key } }));
vi.mock("@/features/workbench/components/AgentPicker", () => ({
  AgentPicker: () => null,
}));
vi.mock("@/features/workbench/components/CreationActions", () => ({
  CreationActions: () => null,
}));
vi.mock("@/features/workbench/components/CreationResultCards", () => ({
  SkillCreationResultCard: () => null,
}));
vi.mock("@/features/workbench/knowledgeDisplay", () => ({
  restoreKnowledgeDisplay: async (scope: unknown) =>
    scope ? { label: "restored" } : null,
}));
vi.mock("@/features/workbench/conversationRestore", () => ({
  resolveRestoredWorkbench: async (conversation: ApiConversationDetail) => ({
    config: conversation.workbench_config,
    version: conversation.workbench_config_version,
    skillNames: {},
  }),
}));
vi.mock("@/features/workbench", async () => {
  const state = await import("@/features/workbench/state");
  return {
    ...state,
    getWorkbenchSendability: () => ({ canSend: true }),
    SkillPicker: () => null,
    previewWorkbenchAgent: vi.fn(),
  };
});
vi.mock("@/services/conversationService", () => ({
  conversationService: {
    getById: vi.fn(),
    getKnowledgeCapabilities: vi.fn(),
    updateWorkbenchConfig: vi.fn(),
  },
}));
vi.mock("@/services/agentConfigService", () => ({
  createSkill: vi.fn(),
  searchAgentInfo: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
function scope(id: number): ConversationKnowledgeScope {
  return {
    schema_version: 1,
    local: { mode: "override", knowledge_ids: [String(id)] },
    aidp: { mode: "inherit", kds_ids: [] },
  };
}
function detail(id: number): ApiConversationDetail {
  return {
    workbench_config: {
      ...config,
      knowledge_scope: scope(id),
    },
    workbench_config_version: id,
    runtime_metadata: { owner: String(id) },
    runtime_metadata_version: id + 1,
    create_time: 0,
    conversation_id: id,
    message: [],
  };
}
function runConfig() {
  return view.setRunConfig.mock.calls.at(-1)![0].custom;
}
beforeEach(() => {
  vi.clearAllMocks();
  view.threadId = "a";
  view.items = [
    { id: "a", remoteId: "101" },
    { id: "b", remoteId: "202" },
  ];
  view.bootstrap = null;
  view.listLoading = false;
  view.threadLoading = false;
  view.running = false;
  view.initialConfigVersion = 7;
  view.nextThread = 0;
  vi.mocked(conversationService.getById).mockImplementation(async (id) =>
    detail(Number(id))
  );
});

it.each([true, false])(
  "preserves the mounted chat during metadata reload while running=%s",
  async (running) => {
    const page = render(<WorkbenchPage />);
    const draft = await screen.findByRole("textbox", {
      name: "workbench draft",
    });
    view.running = running;
    view.listLoading = true;
    page.rerender(<WorkbenchPage />);
    expect(screen.getByRole("textbox", { name: "workbench draft" })).toBe(
      draft
    );
    expect(draft).toHaveValue("Keep my draft");
    view.listLoading = false;
    page.rerender(<WorkbenchPage />);
    expect(screen.getByRole("textbox", { name: "workbench draft" })).toBe(
      draft
    );
  }
);

it("still gates missing active identity and history loading", async () => {
  view.threadId = undefined;
  const page = render(<WorkbenchPage />);
  expect(screen.queryByRole("textbox", { name: "workbench draft" })).toBeNull();
  view.threadId = "a";
  view.threadLoading = true;
  page.rerender(<WorkbenchPage />);
  expect(screen.queryByRole("textbox", { name: "workbench draft" })).toBeNull();
  view.threadLoading = false;
  page.rerender(<WorkbenchPage />);
  expect(
    await screen.findByRole("textbox", { name: "workbench draft" })
  ).toBeVisible();
});

it.each(["pending", "unavailable"])(
  "promotes an executing local thread without rehydrating or remounting its chat when history is %s",
  async (history) => {
    view.threadId = "local-new";
    view.items = [];
    view.initialConfigVersion = 0;
    view.running = true;
    const page = render(<WorkbenchPage />);
    const draft = await screen.findByRole("textbox", {
      name: "workbench draft",
    });
    act(() => view.props!.onRuntimeMetadataChange!({ owner: "live run" }));
    await act(async () => view.props!.onKnowledgeScopeChange!(scope(77)));
    const before = runConfig();
    const pending = deferred<ApiConversationDetail>();
    if (history === "pending") {
      vi.mocked(conversationService.getById).mockReturnValue(pending.promise);
    } else {
      vi.mocked(conversationService.getById).mockRejectedValue(
        new Error("History unavailable")
      );
    }
    act(() => before.onServerConversationId("303"));
    expect(screen.getByRole("textbox", { name: "workbench draft" })).toBe(
      draft
    );
    expect(conversationService.getById).not.toHaveBeenCalled();
    expect(view.props?.knowledgeScope).toEqual(scope(77));
    expect(view.props?.runtimeMetadata).toEqual({ owner: "live run" });
    expect(runConfig()).toMatchObject({
      threadId: "303",
      runtimeMetadata: { owner: "live run" },
      workbenchConfig: before.workbenchConfig,
      workbenchConfigVersion: 1,
    });
    view.running = false;
    view.listLoading = true;
    page.rerender(<WorkbenchPage />);
    view.listLoading = false;
    page.rerender(<WorkbenchPage />);
    expect(screen.getByRole("textbox", { name: "workbench draft" })).toBe(
      draft
    );
    expect(conversationService.getById).not.toHaveBeenCalled();

    vi.mocked(conversationService.getById).mockImplementation(async (id) =>
      detail(Number(id))
    );
    view.threadId = "b";
    view.items = [{ id: "b", remoteId: "202" }];
    page.rerender(<WorkbenchPage />);
    await waitFor(() =>
      expect(view.props?.runtimeMetadata).toEqual({ owner: "202" })
    );
    view.threadId = "local-new";
    page.rerender(<WorkbenchPage />);
    await waitFor(() =>
      expect(view.props?.runtimeMetadata).toEqual({ owner: "303" })
    );
    expect(conversationService.getById).toHaveBeenCalledWith("303");
    expect(view.props?.knowledgeScope).toEqual(scope(303));
  }
);

it("never publishes the previous conversation's knowledge or dirty metadata when switching", async () => {
  const page = render(<WorkbenchPage />);
  await waitFor(() =>
    expect(view.props?.runtimeMetadata).toEqual({ owner: "101" })
  );
  act(() => view.props!.onRuntimeMetadataChange!({ owner: "edited-a" }));
  const acknowledgeA = runConfig().onRuntimeMetadataSent;
  expect(runConfig()).toMatchObject({
    threadId: "101",
    runtimeMetadata: { owner: "edited-a" },
    runtimeMetadataVersion: 102,
  });
  const pendingB = deferred<ApiConversationDetail>();
  vi.mocked(conversationService.getById).mockReturnValue(pendingB.promise);
  view.setRunConfig.mockClear();
  view.threadId = "b";
  page.rerender(<WorkbenchPage />);
  expect(view.props?.runtimeMetadata).toEqual({});
  expect(view.props?.knowledgeScope).toBeNull();
  for (const [published] of view.setRunConfig.mock.calls) {
    expect(published.custom.threadId).toBe("202");
    expect(published.custom.runtimeMetadata).toBeUndefined();
    expect(published.custom.knowledgeScope).toBeUndefined();
  }
  act(() => view.props!.onRuntimeMetadataChange!({ owner: "edited-b" }));
  act(() => acknowledgeA(999));
  expect(runConfig().runtimeMetadata).toEqual({ owner: "edited-b" });
  await act(async () => pendingB.resolve(detail(202)));
  expect(runConfig().threadId).toBe("202");
  expect(view.props?.knowledgeScope).toEqual(
    detail(202).workbench_config!.knowledge_scope
  );
});

it("ignores delayed loads and saves from an inactive conversation", async () => {
  const pendingA = deferred<ApiConversationDetail>();
  vi.mocked(conversationService.getById).mockImplementation((id) =>
    id === "101" ? pendingA.promise : Promise.resolve(detail(202))
  );
  const page = render(<WorkbenchPage />);
  view.threadId = "b";
  page.rerender(<WorkbenchPage />);
  await waitFor(() =>
    expect(view.props?.runtimeMetadata).toEqual({ owner: "202" })
  );
  await act(async () => pendingA.resolve(detail(101)));
  expect(view.props?.runtimeMetadata).toEqual({ owner: "202" });
  expect(runConfig().workbenchConfigVersion).toBe(202);
  const saveB =
    deferred<
      Awaited<ReturnType<typeof conversationService.updateWorkbenchConfig>>
    >();
  vi.mocked(conversationService.updateWorkbenchConfig).mockReturnValue(
    saveB.promise
  );
  let saving!: Promise<unknown>;
  await act(async () => {
    saving = Promise.resolve(
      view.props!.onKnowledgeScopeChange!(scope(77))
    ).catch((e: Error) => e);
  });
  view.threadId = "a";
  page.rerender(<WorkbenchPage />);
  await waitFor(() =>
    expect(view.props?.runtimeMetadata).toEqual({ owner: "101" })
  );
  await act(async () => {
    saveB.resolve({
      workbench_config: { ...config, requested_output_tokens: 999 },
      workbench_config_version: 999,
    });
    await saving;
  });
  expect(runConfig().threadId).toBe("101");
  expect(runConfig().workbenchConfig.requested_output_tokens).toBe(1234);
  expect(runConfig().workbenchConfigVersion).toBe(101);
});

it("a version conflict bypasses shared history and preserves input and model parameters", async () => {
  render(<WorkbenchPage />);
  await waitFor(() =>
    expect(view.props?.runtimeMetadata).toEqual({ owner: "101" })
  );
  expect(conversationService.getById).toHaveBeenCalledTimes(1);
  const fresh = { ...detail(101), workbench_config_version: 999 };
  vi.mocked(conversationService.getById).mockResolvedValue(fresh);
  await act(async () =>
    runConfig().onWorkbenchConfigConflict("Keep this question")
  );
  expect(conversationService.getById).toHaveBeenCalledTimes(2);
  expect(runConfig().workbenchConfigVersion).toBe(999);
  expect(runConfig().workbenchConfig.requested_output_tokens).toBe(config.requested_output_tokens);
  expect(runtime.thread.composer.setText).toHaveBeenCalledWith(
    "Keep this question"
  );
});

it("uses the server-issued ID first and preserves exact model config and version", async () => {
  view.threadId = "local";
  view.items = [{ id: "local", remoteId: "" }];
  render(<WorkbenchPage />);
  expect(runConfig().threadId).toBeUndefined();
  await act(async () => runConfig().onServerConversationId("303"));
  await waitFor(() => expect(runConfig().threadId).toBe("303"));
  expect(runConfig().workbenchConfig.requested_output_tokens).toBe(1234);
  expect(runConfig().workbenchConfigVersion).toBe(7);
  act(() => runConfig().onWorkbenchConfigVersion(8));
  expect(runConfig().workbenchConfigVersion).toBe(8);
  expect(view.props?.conversationId).toBe(303);
  expect(runConfig().workbenchConfig).not.toHaveProperty("generation_config");
});

it("restores a local chat snapshot after entering and leaving creation", async () => {
  view.threadId = "local";
  view.items = [{ id: "local", remoteId: "" }];
  const page = render(<WorkbenchPage />);
  await act(async () => {
    await view.props!.onKnowledgeScopeChange!(scope(7));
  });
  const snapshot = structuredClone(runConfig().workbenchConfig);
  await act(async () => {
    (
      view.props!.workbenchPresentation!.actions as React.ReactElement<{
        onSelect: (mode: string) => void;
      }>
    ).props.onSelect("skill_create");
  });
  page.rerender(<WorkbenchPage />);
  expect(runConfig().runtimeMode).toBe("nl2skill");
  expect(runConfig().creationWorkbenchConfig.generation_config).toEqual(
    snapshot.generation_config
  );
  await act(async () => view.props!.workbenchPresentation!.onExitCreation!());
  page.rerender(<WorkbenchPage />);
  expect(view.threadId).toBe("local");
  expect(runConfig().workbenchConfig).toEqual(snapshot);
  expect(view.props?.knowledgeScope).toEqual(scope(7));
});

it("restores generated local Skill files after visiting another creation thread", async () => {
  view.threadId = "local";
  view.items = [{ id: "local", remoteId: "" }];
  const page = render(<WorkbenchPage />);
  const selectCreation = async (mode: string) => {
    await act(async () => {
      (
        view.props!.workbenchPresentation!.actions as React.ReactElement<{
          onSelect: (mode: string) => void;
        }>
      ).props.onSelect(mode);
    });
    page.rerender(<WorkbenchPage />);
  };
  await selectCreation("skill_create");
  const skillThread = view.threadId;
  act(() =>
    runConfig().onNl2SkillEvent({
      type: "skill_body",
      content: "saved skill file",
    })
  );
  expect(view.props?.skillFiles).toEqual([
    { path: "SKILL.md", content: "saved skill file" },
  ]);
  await selectCreation("agent_create");
  expect(runConfig().runtimeMode).toBe("nl2agent");
  view.threadId = skillThread;
  page.rerender(<WorkbenchPage />);
  await waitFor(() => expect(runConfig().runtimeMode).toBe("nl2skill"));
  expect(view.props?.skillFiles).toEqual([
    { path: "SKILL.md", content: "saved skill file" },
  ]);
  expect(runConfig().draftSnapshot.files).toEqual([
    { path: "SKILL.md", content: "saved skill file" },
  ]);
  expect(runConfig().creationWorkbenchConfig.requested_output_tokens).toBe(
    1234
  );
  expect(runConfig().creationWorkbenchConfig).not.toHaveProperty(
    "generation_config"
  );
});

it("clears unavailable capabilities and ignores a removed Agent's delayed response", async () => {
  const pending =
    deferred<
      Awaited<ReturnType<typeof conversationService.getKnowledgeCapabilities>>
    >();
  vi.mocked(conversationService.getKnowledgeCapabilities).mockReturnValue(
    pending.promise
  );
  view.bootstrap = { generic_agent: { agent_id: 5, version_no: 2 } };
  const page = render(<WorkbenchPage />);
  expect(
    conversationService.getKnowledgeCapabilities
  ).toHaveBeenCalledExactlyOnceWith(5, 2);
  view.bootstrap = null;
  page.rerender(<WorkbenchPage />);
  await act(async () =>
    pending.resolve({
      agent_id: 5,
      version_no: 2,
      sources: {
        local: {
          enabled: true,
          max_select: 5,
          requires_same_embedding_model: false,
          default_summary: "",
          default_knowledge_ids: [],
          default_range_values: [],
        },
        aidp: {
          enabled: false,
          max_select: 0,
          default_summary: "",
          default_knowledge_ids: [],
          default_range_values: [],
        },
      },
    })
  );
  expect(view.props?.knowledgeCapabilities).toBeNull();
  vi.mocked(conversationService.getKnowledgeCapabilities).mockRejectedValue(
    new Error("offline")
  );
  view.bootstrap = { generic_agent: { agent_id: 6, version_no: 3 } };
  page.rerender(<WorkbenchPage />);
  await waitFor(() =>
    expect(conversationService.getKnowledgeCapabilities).toHaveBeenCalledWith(
      6,
      3
    )
  );
  expect(view.props?.knowledgeCapabilities).toBeNull();
});

it.each([true, false])(
  "refreshes a policy-only creator save without changing session policy (%s)",
  async (enabled) => {
    view.threadId = "local";
    view.items = [{ id: "local", remoteId: "" }];
    const page = render(<WorkbenchPage />);
    await act(async () => {
      (
        view.props!.workbenchPresentation!.actions as React.ReactElement<{
          onSelect: (mode: string) => void;
        }>
      ).props.onSelect("agent_create");
    });
    page.rerender(<WorkbenchPage />);
    const agent = {
      id: "42",
      name: "policy_assistant",
      enable_protocol_repair_retry: enabled,
    };
    vi.mocked(searchAgentInfo).mockResolvedValue({
      success: true,
      data: agent,
    } as never);
    const replace = vi
      .spyOn(useAgentStore.getState(), "replaceServerSnapshot")
      .mockReturnValue(true);
    await act(async () => {
      runConfig().onNl2AgentState({
        event: "agent_draft_fields_saved",
        agent_id: 42,
        updated_fields: ["enable_protocol_repair_retry"],
      });
    });
    expect(searchAgentInfo).toHaveBeenCalledWith(42, undefined, 0);
    expect(replace).toHaveBeenCalledWith(42, agent);
    expect(view.markGenerationCompleted).not.toHaveBeenCalled();
    expect(view.markCompletionSynced).not.toHaveBeenCalled();
    expect(runConfig().creationWorkbenchConfig).not.toHaveProperty(
      "execution_config"
    );
  }
);

it("preserves completion synchronization after supporting partial policy saves", async () => {
  view.threadId = "local";
  view.items = [{ id: "local", remoteId: "" }];
  const page = render(<WorkbenchPage />);
  await act(async () => {
    (
      view.props!.workbenchPresentation!.actions as React.ReactElement<{
        onSelect: (mode: string) => void;
      }>
    ).props.onSelect("agent_create");
  });
  page.rerender(<WorkbenchPage />);
  const agent = {
    id: "42",
    name: "policy_assistant",
    enable_protocol_repair_retry: true,
  };
  vi.mocked(searchAgentInfo).mockResolvedValue({
    success: true,
    data: agent,
  } as never);
  vi.spyOn(useAgentStore.getState(), "replaceServerSnapshot").mockReturnValue(
    true
  );
  await act(async () =>
    runConfig().onNl2AgentState({
      event: "agent_generation_completed",
      agent_id: 42,
    })
  );
  expect(view.markGenerationCompleted).toHaveBeenCalledExactlyOnceWith(42);
  expect(view.markCompletionSynced).toHaveBeenCalledExactlyOnceWith(42);
});

it("serializes creator snapshot reads so delayed policy saves cannot overwrite the latest value", async () => {
  view.threadId = "local";
  view.items = [{ id: "local", remoteId: "" }];
  const page = render(<WorkbenchPage />);
  await act(async () => {
    (
      view.props!.workbenchPresentation!.actions as React.ReactElement<{
        onSelect: (mode: string) => void;
      }>
    ).props.onSelect("agent_create");
  });
  page.rerender(<WorkbenchPage />);
  const first = deferred<Awaited<ReturnType<typeof searchAgentInfo>>>();
  const enabled = {
    id: "42",
    name: "policy_assistant",
    enable_protocol_repair_retry: true,
  };
  const disabled = { ...enabled, enable_protocol_repair_retry: false };
  vi.mocked(searchAgentInfo)
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce({ success: true, data: disabled } as never);
  const replace = vi
    .spyOn(useAgentStore.getState(), "replaceServerSnapshot")
    .mockReturnValue(true);
  const event = {
    event: "agent_draft_fields_saved",
    agent_id: 42,
    updated_fields: ["enable_protocol_repair_retry"],
  };
  await act(async () => {
    runConfig().onNl2AgentState(event);
    runConfig().onNl2AgentState(event);
  });
  expect(searchAgentInfo).toHaveBeenCalledTimes(1);
  await act(async () =>
    first.resolve({ success: true, data: enabled } as never)
  );
  await waitFor(() => expect(replace).toHaveBeenCalledTimes(2));
  expect(
    replace.mock.calls.map((args) => args[1].enable_protocol_repair_retry)
  ).toEqual([true, false]);
  expect(view.markGenerationCompleted).not.toHaveBeenCalled();
});
