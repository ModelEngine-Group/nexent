"use client";

import { Avatar } from "antd";
import { Lightbulb } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import type { Agent } from "@/types/agentConfig";
import { API_ENDPOINTS } from "@/services/api";
import { getAgentUploadedIconRevision } from "@/lib/chat/agentIconUtils";
import { DefaultAgentAvatar } from "../DefaultAgentAvatar";

interface AgentDebugWelcomeProps {
  agent: Agent;
}

export function AgentDebugWelcome({ agent }: AgentDebugWelcomeProps) {
  const [failedIcon, setFailedIcon] = useState<string>();
  const iconSource = agent.icon_url
    ? API_ENDPOINTS.agent.icon(
        Number(agent.id),
        getAgentUploadedIconRevision(agent.icon_url)
      )
    : undefined;

  return (
    <div data-testid="agent-debug-welcome" className="agent-debug-welcome">
      <div className="agent-debug-welcome-title">
        <Avatar
          size={72}
          src={iconSource !== failedIcon ? iconSource : undefined}
          icon={<DefaultAgentAvatar size={72} />}
          className="!shrink-0 !bg-transparent"
          onError={() => {
            setFailedIcon(iconSource);
            return false;
          }}
        />
        <h1>{agent.display_name || agent.name}</h1>
      </div>
      <p className="agent-debug-greeting">
        {agent.greeting_message || agent.description}
      </p>
    </div>
  );
}

interface AgentDebugSuggestionsProps {
  questions?: readonly string[];
  onSelect: (question: string) => void;
}

export function AgentDebugSuggestions({
  questions,
  onSelect,
}: AgentDebugSuggestionsProps) {
  const { t } = useTranslation("common");
  if (!questions?.length) return null;
  return (
    <section
      data-testid="agent-debug-suggestions"
      className="agent-debug-suggestions"
    >
      <h2>{t("agent.debug.tryQuestions")}</h2>
      <div className="agent-debug-question-list">
        {questions.map((question, index) => (
          <button
            key={index}
            type="button"
            onClick={() => onSelect(question)}
            title={question}
          >
            <Lightbulb size={16} className="shrink-0" />
            <span className="min-w-0 break-words">{question}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
