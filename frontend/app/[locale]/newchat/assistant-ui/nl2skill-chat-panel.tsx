// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type FC,
} from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { message } from "antd";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import type { SkillFileContent } from "@/types/skill";
import { useCreatorModelControls } from "@/features/model-controls/useCreatorModelControls";
import { useCreatorHistories } from "@/hooks/chat/useCreatorHistories";
import { conversationService } from "@/services/conversationService";
import {
  remoteChatModelAdapter,
  type Nl2SkillStreamEvent,
} from "../adapter/remote-chat-model-adapter";
import { Chat } from "./chat";
import { CreatorHistoryToolbar } from "./creator-history-toolbar";

interface Nl2SkillChatPanelProps {
  getDraftSnapshot: () => Record<string, unknown>;
  targetSkillId?: number;
  onConversationId?: (id: string | undefined) => void;
  onStreamEvent: (event: Nl2SkillStreamEvent) => void;
  language: "zh" | "en";
  availableFiles: readonly SkillFileContent[];
  onSkillFileSelect?: (path: string) => void;
}

const NL2SKILL_DISPLAY_BASE: Agent = {
  id: "__skill_creator__",
  name: "NL2Skill",
  description: "",
  model: "main_model",
  max_step: 5,
  provide_run_summary: false,
  tools: [],
};

const Nl2SkillChatSession: FC<Nl2SkillChatPanelProps> = ({
  getDraftSnapshot,
  targetSkillId,
  onConversationId,
  onStreamEvent,
  language,
  availableFiles,
  onSkillFileSelect,
}) => {
  const { t } = useTranslation("common");
  const historyRef = useRef<{ id?: string; active: boolean }>({ active: true });
  const history = useCreatorHistories("skill", targetSkillId ?? null);
  const refreshHistory = history.refresh;
  const [selectedId, setSelectedId] = useState<string>();
  const [restoring, setRestoring] = useState(false);
  const loadGeneration = useRef({ value: 0 });
  useEffect(() => {
    const session = historyRef.current;
    const generation = loadGeneration.current;
    session.active = true;
    return () => {
      session.active = false;
      generation.value++;
    };
  }, []);
  const modelControls = useCreatorModelControls(
    NL2SKILL_DISPLAY_BASE,
    "nl2skill",
    "skill:create"
  );

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run(options) {
        if (!modelControls.canSend || restoring) return;
        const currentHistory = historyRef.current;
        try {
          const result = remoteChatModelAdapter.run({
            ...options,
            runConfig: {
              custom: {
                ...options.runConfig?.custom,
                runtimeMode: "nl2skill",
                threadId: currentHistory.id,
                creationTarget: targetSkillId
                  ? { type: "skill", id: targetSkillId }
                  : undefined,
                onServerConversationId: (id: string) => {
                  if (!currentHistory.active) return;
                  currentHistory.id = id;
                  setSelectedId(id);
                  onConversationId?.(id);
                  void refreshHistory();
                },
                draftSnapshot: getDraftSnapshot(),
                language,
                onNl2SkillEvent: onStreamEvent,
                turnModelControls: modelControls.snapshot,
              },
            },
          });
          if ("then" in result) yield await result;
          else yield* result;
        } finally {
          void refreshHistory();
        }
      },
    }),
    [
      getDraftSnapshot,
      targetSkillId,
      onConversationId,
      language,
      onStreamEvent,
      modelControls.snapshot,
      modelControls.canSend,
      refreshHistory,
      restoring,
    ]
  );
  const runtime = useLocalRuntime(adapter);
  const isRunning = useSyncExternalStore(
    runtime.thread.subscribe,
    () => runtime.thread.getState().isRunning,
    () => false
  );
  const selectHistory = async (id: number) => {
    if (runtime.thread.getState().isRunning || !targetSkillId) return;
    const generation = ++loadGeneration.current.value;
    setRestoring(true);
    try {
      const detail = await conversationService.getById(String(id));
      if (generation !== loadGeneration.current.value) return;
      if (
        detail.agent_system_key !== "nl2skill_main" ||
        detail.target?.type !== "skill" ||
        detail.target.id !== targetSkillId
      ) {
        throw new Error("Creator history target mismatch");
      }
      const { RemoteConversationHistoryAdapter } =
        await import("../adapter/conversation-thread-list-adapter");
      if (generation !== loadGeneration.current.value) return;
      const saved = await new RemoteConversationHistoryAdapter(
        () => String(id),
        async () => ({ remoteId: String(id), externalId: String(id) }),
        async () => detail
      ).load();
      if (generation !== loadGeneration.current.value) return;
      await runtime.thread.composer.reset();
      if (generation !== loadGeneration.current.value) return;
      runtime.thread.import(saved);
      historyRef.current.id = String(id);
      setSelectedId(String(id));
      onConversationId?.(String(id));
    } catch {
      if (generation === loadGeneration.current.value)
        message.error(t("nl2agent.history.restoreFailed"));
    } finally {
      if (generation === loadGeneration.current.value) setRestoring(false);
    }
  };
  const newConversation = async () => {
    if (runtime.thread.getState().isRunning) return;
    const generation = ++loadGeneration.current.value;
    setRestoring(true);
    try {
      await runtime.thread.composer.reset();
      if (generation !== loadGeneration.current.value) return;
      runtime.thread.reset();
      historyRef.current.id = undefined;
      setSelectedId(undefined);
      onConversationId?.(undefined);
    } catch {
      if (generation === loadGeneration.current.value)
        message.error(t("nl2agent.history.newFailed"));
    } finally {
      if (generation === loadGeneration.current.value) setRestoring(false);
    }
  };
  const assistantTitle = t("skillManagement.tabs.interactive");
  const displayAgent: Agent = {
    ...NL2SKILL_DISPLAY_BASE,
    display_name: assistantTitle,
    description: t("skillManagement.chat.createGreetingTitle"),
  };

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <CreatorHistoryToolbar
            history={history}
            resourceKind="skill"
            selectedId={selectedId}
            disabled={isRunning}
            restoring={restoring}
            onSelect={selectHistory}
            onNew={newConversation}
          />
          <div className="min-h-0 flex-1">
            <Chat
              selectedAgent={displayAgent}
              generatedTitle={assistantTitle}
              welcomeTitle={t("skillManagement.chat.createWelcomeTitle")}
              isLoadingAgents={false}
              {...modelControls}
              modelSelectionScope="tenant"
              showModelSelector
              readOnly={restoring || !modelControls.canCreate}
              variant="embedded"
              skillFiles={availableFiles}
              onSkillFileSelect={onSkillFileSelect}
            />
          </div>
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};

export const Nl2SkillChatPanel: FC<Nl2SkillChatPanelProps> = (props) => (
  <Nl2SkillChatSession key={props.targetSkillId ?? "new"} {...props} />
);
