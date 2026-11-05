// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import {
  ComposerAttachment,
  ComposerDictation,
} from "@/app/newchat/assistant-ui/composer-tools";
import { Thread } from "@/app/newchat/assistant-ui/thread";
import type { ChatMode } from "@/app/newchat/assistant-ui/composer";
import type { Agent } from "@/types/agentConfig";
import { AgentDebugWelcome } from "./agent-debug-welcome";

interface DebugConversationProps {
  agent: Agent;
  chatMode: ChatMode;
  onChatModeChange: (mode: ChatMode) => void;
  selectedModelId?: string;
  onModelChange?: (id: string) => void;
  dictationConfigured?: boolean;
  comparison?: boolean;
  onSelectQuestion?: (question: string) => void;
  onSourcesPanelOpen?: () => void;
  sourcesPanelCloseEpoch?: number;
}

export function DebugConversation({
  agent,
  chatMode,
  onChatModeChange,
  selectedModelId,
  onModelChange,
  dictationConfigured = false,
  comparison = false,
  onSelectQuestion,
  onSourcesPanelOpen,
  sourcesPanelCloseEpoch,
}: DebugConversationProps) {
  const aui = useAui();
  const isRunning = useAuiState((state) => state.thread.isRunning);
  return (
    <Thread
      agent={agent}
      chatMode={chatMode}
      onChatModeChange={onChatModeChange}
      selectedModelId={selectedModelId}
      onModelChange={onModelChange}
      showModelSelector={!comparison}
      showComposer={!comparison}
      variant={comparison ? "embedded" : "default"}
      showConversationTitle={false}
      debugLayout
      onSourcesPanelOpen={onSourcesPanelOpen}
      sourcesPanelCloseEpoch={sourcesPanelCloseEpoch}
      composerTools={
        <>
          <ComposerAttachment />
          <ComposerDictation configured={dictationConfigured} />
        </>
      }
      welcomeContent={
        <AgentDebugWelcome
          agent={agent}
          disabled={isRunning}
          onSelectQuestion={
            onSelectQuestion ?? ((question) => aui.composer().setText(question))
          }
        />
      }
    />
  );
}
