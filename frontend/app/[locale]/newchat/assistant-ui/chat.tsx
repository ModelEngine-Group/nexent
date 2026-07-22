"use client";

import type { FC } from "react";
import { useCallback } from "react";
import { Thread } from "./thread";
import { AgentLandingPage } from "./agent-landing";
import type { Agent } from "@/types/agentConfig";

export interface ChatProps {
  generatedTitle?: string;
  isLoadingAgents?: boolean;
  selectedAgent: Agent | null;
  onAgentSelected?: (agent: Agent) => void;
  onBack: () => void;
}

const AgentsLoadingState: FC = () => (
  <div className="flex h-full items-center justify-center">
    <div className="flex flex-col items-center gap-4">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      <p className="text-sm text-muted-foreground">Loading agents...</p>
    </div>
  </div>
);

export const Chat: FC<ChatProps> = ({
  generatedTitle,
  isLoadingAgents = false,
  selectedAgent,
  onAgentSelected,
  onBack,
}) => {
  const handleSelectAgent = useCallback(
    (agent: Agent) => {
      onAgentSelected?.(agent);
    },
    [onAgentSelected],
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

  return <Thread agent={selectedAgent} generatedTitle={generatedTitle} onBack={onBack} />;
};
