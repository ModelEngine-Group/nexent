// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReasoningEffort } from "@/types/modelConfig";

import type { FC, ReactNode } from "react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Thread, type WelcomeSuggestion } from "./thread";
import type { ChatMode } from "./composer";
import { AgentLandingPage } from "./agent-landing";
import type { Agent } from "@/types/agentConfig";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import type { SkillFileContent } from "@/types/skill";

export interface ChatProps {
  generatedTitle?: string;
  welcomeTitle?: string;
  welcomeSuggestions?: readonly WelcomeSuggestion[];
  conversationId?: number;
  isLoadingAgents?: boolean;
  selectedAgent: Agent | null;
  onAgentSelected?: (agent: Agent) => void;
  onBack?: () => void;
  chatMode?: ChatMode;
  onChatModeChange?: (mode: ChatMode) => void;
  showModelSelector?: boolean;
  modelSelectionScope?: "agent" | "tenant";
  fallbackAgentName?: string;
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  showConversationTitle?: boolean;
  composerTools?: ReactNode;
  knowledgeScope?: ConversationKnowledgeScope | null;
  knowledgePreview?: KnowledgeScopeEffectivePreview | null;
  knowledgeCapabilities?: KnowledgeCapabilities | null;
  onKnowledgeScopeChange?: (
    scope: ConversationKnowledgeScope | null,
    preview?: KnowledgeScopeEffectivePreview | null
  ) => Promise<void> | void;
  variant?: "default" | "embedded";
  skillFiles?: readonly SkillFileContent[];
  onSkillFileSelect?: (path: string) => void;
  runtimeMetadata?: Record<string, unknown>;
  onRuntimeMetadataChange?: (value: Record<string, unknown>) => void;
  readOnly?: boolean;
  interactionContent?: ReactNode;
  readOnlyReason?: string;
  landingContent?: ReactNode;
  /** Opt into the redesigned NewChat presentation. */
  newChatDesign?: boolean;
  workbenchPresentation?: import("@/features/workbench/types").WorkbenchComposerPresentation;
  workbenchResources?: import("@/features/workbench/types").WorkbenchResourceControls;
  onRemoveWorkbenchSkill?: (skillId: number) => void;
  onOpenWorkbenchSkillPicker?: () => void;
}

const AgentsLoadingState: FC = () => {
  const { t } = useTranslation();

  return (
    <div className="flex h-full items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">
          {t("chat.chat.loadingAgents")}
        </p>
      </div>
    </div>
  );
};

export const Chat: FC<ChatProps> = ({
  generatedTitle,
  welcomeTitle,
  welcomeSuggestions,
  conversationId,
  isLoadingAgents = false,
  selectedAgent,
  onAgentSelected,
  onBack,
  chatMode = "execution",
  onChatModeChange,
  showModelSelector = true,
  modelSelectionScope = "agent",
  fallbackAgentName = "Nexent Workbench",
  selectedModelId,
  onModelChange,
  showConversationTitle = true,
  composerTools,
  knowledgeScope = null,
  knowledgePreview = null,
  knowledgeCapabilities = null,
  onKnowledgeScopeChange,
  variant = "default",
  skillFiles,
  onSkillFileSelect,
  runtimeMetadata = {},
  onRuntimeMetadataChange,
  readOnly = false,
  interactionContent,
  readOnlyReason,
  landingContent,
  newChatDesign = false,
  workbenchPresentation,
  workbenchResources,
  onRemoveWorkbenchSkill,
  onOpenWorkbenchSkillPicker,
}) => {
  const handleSelectAgent = useCallback(
    (agent: Agent) => {
      onAgentSelected?.(agent);
    },
    [onAgentSelected]
  );
  const workbenchPlaceholderAgent = useMemo<Agent>(
    () => ({
      id: "__workbench_empty__",
      name: fallbackAgentName,
      display_name: fallbackAgentName,
      description: "",
      model: "",
      max_step: 8,
      provide_run_summary: false,
      tools: [],
    }),
    [fallbackAgentName]
  );

  if (!selectedAgent) {
    if (isLoadingAgents) {
      return <AgentsLoadingState />;
    }
    if (workbenchPresentation || landingContent) {
      return (
        <Thread
          agent={workbenchPlaceholderAgent}
          generatedTitle={generatedTitle}
          conversationId={conversationId}
          newChatDesign={newChatDesign}
          welcomeContent={landingContent}
          selectedModelId={selectedModelId}
          onModelChange={onModelChange}
          showModelSelector={showModelSelector}
          modelSelectionScope={modelSelectionScope}
          chatMode={chatMode}
          onChatModeChange={onChatModeChange}
          composerTools={composerTools}
          readOnly={readOnly}
          readOnlyReason={readOnlyReason}
          interactionContent={interactionContent}
          showConversationTitle={showConversationTitle}
          workbenchPresentation={workbenchPresentation}
          workbenchResources={workbenchResources}
          onOpenWorkbenchSkillPicker={onOpenWorkbenchSkillPicker}
          onRemoveWorkbenchSkill={onRemoveWorkbenchSkill}
          skillFiles={skillFiles}
          knowledgeScope={knowledgeScope}
          knowledgePreview={knowledgePreview}
          knowledgeCapabilities={knowledgeCapabilities}
          onKnowledgeScopeChange={onKnowledgeScopeChange}
        />
      );
    }
    return (
      <AgentLandingPage
        onSelectAgent={(agent) => handleSelectAgent(agent as unknown as Agent)}
      />
    );
  }

  return (
    <Thread
      agent={selectedAgent}
      generatedTitle={generatedTitle}
      welcomeTitle={welcomeTitle}
      welcomeSuggestions={welcomeSuggestions}
      conversationId={conversationId}
      newChatDesign={newChatDesign}
      onBack={onBack}
      chatMode={chatMode}
      onChatModeChange={onChatModeChange}
      showModelSelector={showModelSelector}
      modelSelectionScope={modelSelectionScope}
      selectedModelId={selectedModelId}
      onModelChange={onModelChange}
      showConversationTitle={showConversationTitle}
      composerTools={composerTools}
      knowledgeScope={knowledgeScope}
      knowledgePreview={knowledgePreview}
      knowledgeCapabilities={knowledgeCapabilities}
      onKnowledgeScopeChange={onKnowledgeScopeChange}
      variant={variant}
      skillFiles={skillFiles}
      onSkillFileSelect={onSkillFileSelect}
      runtimeMetadata={runtimeMetadata}
      onRuntimeMetadataChange={onRuntimeMetadataChange}
      readOnly={readOnly}
      interactionContent={interactionContent}
      readOnlyReason={readOnlyReason}
      workbenchPresentation={workbenchPresentation}
      workbenchResources={workbenchResources}
      onRemoveWorkbenchSkill={onRemoveWorkbenchSkill}
      onOpenWorkbenchSkillPicker={onOpenWorkbenchSkillPicker}
    />
  );
};
