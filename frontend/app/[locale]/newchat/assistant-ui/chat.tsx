"use client";

import type { FC, ReactNode } from "react";
import { useCallback } from "react";
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
  selectedModelId?: string;
  onModelChange?: (modelId: string) => void;
  showConversationTitle?: boolean;
  isDictationConfigured?: boolean;
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
  readOnlyReason?: string;
  landingContent?: ReactNode;
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
  onChatModeChange = () => undefined,
  showModelSelector = true,
  selectedModelId,
  onModelChange,
  showConversationTitle = true,
  isDictationConfigured = false,
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
  readOnlyReason,
  landingContent,
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

  if (!selectedAgent) {
    if (isLoadingAgents) {
      return <AgentsLoadingState />;
    }
    if (workbenchPresentation || landingContent) {
      return (
        <Thread
          agent={{
            id: "__workbench_empty__",
            name: "智能体工作台",
            description: "",
            model: "",
            max_step: 8,
            provide_run_summary: false,
            tools: [],
          }}
          welcomeContent={landingContent}
          selectedModelId={selectedModelId}
          onModelChange={onModelChange}
          showModelSelector={showModelSelector}
          chatMode={chatMode}
          onChatModeChange={onChatModeChange}
          isDictationConfigured={isDictationConfigured}
          readOnly={readOnly}
          readOnlyReason={readOnlyReason}
          showConversationTitle={false}
          workbenchPresentation={workbenchPresentation}
          workbenchResources={workbenchResources}
          onOpenWorkbenchSkillPicker={onOpenWorkbenchSkillPicker}
          onRemoveWorkbenchSkill={onRemoveWorkbenchSkill}
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
      onBack={onBack}
      chatMode={chatMode}
      onChatModeChange={onChatModeChange}
      showModelSelector={showModelSelector}
      selectedModelId={selectedModelId}
      onModelChange={onModelChange}
      showConversationTitle={showConversationTitle}
      isDictationConfigured={isDictationConfigured}
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
      readOnlyReason={readOnlyReason}
      workbenchPresentation={workbenchPresentation}
      workbenchResources={workbenchResources}
      onRemoveWorkbenchSkill={onRemoveWorkbenchSkill}
      onOpenWorkbenchSkillPicker={onOpenWorkbenchSkillPicker}
    />
  );
};
