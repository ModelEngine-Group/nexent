"use client";

import type { FC } from "react";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Thread } from "./thread";
import type { ChatMode } from "./composer";
import { AgentLandingPage } from "./agent-landing";
import type { Agent } from "@/types/agentConfig";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
} from "@/types/knowledgeScope";
import type { SkillFileContent } from "@/types/skill";

export interface ChatProps {
  generatedTitle?: string;
  conversationId?: number;
  isLoadingAgents?: boolean;
  selectedAgent: Agent | null;
  onAgentSelected?: (agent: Agent) => void;
  onBack?: () => void;
  chatMode?: ChatMode;
  onChatModeChange?: (mode: ChatMode) => void;
  showModelSelector?: boolean;
  isDictationConfigured?: boolean;
  knowledgeScope?: ConversationKnowledgeScope | null;
  knowledgeCapabilities?: KnowledgeCapabilities | null;
  onKnowledgeScopeChange?: (
    scope: ConversationKnowledgeScope | null
  ) => Promise<void> | void;
  variant?: "default" | "embedded";
  skillFiles?: readonly SkillFileContent[];
  onSkillFileSelect?: (path: string) => void;
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
  conversationId,
  isLoadingAgents = false,
  selectedAgent,
  onAgentSelected,
  onBack,
  chatMode = "execution",
  onChatModeChange = () => undefined,
  showModelSelector = true,
  isDictationConfigured = false,
  knowledgeScope = null,
  knowledgeCapabilities = null,
  onKnowledgeScopeChange,
  variant = "default",
  skillFiles,
  onSkillFileSelect,
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
      conversationId={conversationId}
      onBack={onBack}
      chatMode={chatMode}
      onChatModeChange={onChatModeChange}
      showModelSelector={showModelSelector}
      isDictationConfigured={isDictationConfigured}
      knowledgeScope={knowledgeScope}
      knowledgeCapabilities={knowledgeCapabilities}
      onKnowledgeScopeChange={onKnowledgeScopeChange}
      variant={variant}
      skillFiles={skillFiles}
      onSkillFileSelect={onSkillFileSelect}
    />
  );
};
