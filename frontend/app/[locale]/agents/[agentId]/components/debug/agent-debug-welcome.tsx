// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Avatar } from "antd";
import { createElement, useState } from "react";
import type { Agent } from "@/types/agentConfig";
import { AgentWelcome } from "@/components/agent/agent-welcome";
import { TextSuggestion } from "@/components/agent/agent-suggestion";
import { API_ENDPOINTS } from "@/services/api";
import {
  getAgentIcon,
  getAgentUploadedIconRevision,
} from "@/lib/chat/agentIconUtils";

interface AgentDebugWelcomeProps {
  agent: Agent;
  onSelectQuestion?: (question: string) => void;
  disabled?: boolean;
}

export function AgentDebugWelcome({
  agent,
  onSelectQuestion,
  disabled,
}: AgentDebugWelcomeProps) {
  const [failedIcon, setFailedIcon] = useState<string>();
  const iconSource = agent.icon_url
    ? API_ENDPOINTS.agent.icon(
        Number(agent.id),
        getAgentUploadedIconRevision(agent.icon_url)
      )
    : undefined;

  return (
    <div
      data-testid="agent-debug-welcome"
      className="flex min-h-full shrink-0 flex-col"
    >
      <AgentWelcome
        className="h-auto flex-1 shrink-0"
        title={agent.display_name || agent.name}
        greeting={agent.greeting_message || agent.description}
        icon={
          <Avatar
            size={56}
            src={iconSource !== failedIcon ? iconSource : undefined}
            icon={createElement(getAgentIcon(agent), { size: 28 })}
            className="!shrink-0 !bg-primary/10 !text-primary"
            onError={() => {
              setFailedIcon(iconSource);
              return false;
            }}
          />
        }
      >
        {onSelectQuestion && (
          <AgentDebugSuggestions
            questions={agent.example_questions}
            onSelect={onSelectQuestion}
            disabled={disabled}
          />
        )}
      </AgentWelcome>
    </div>
  );
}

interface AgentDebugSuggestionsProps {
  questions?: readonly string[];
  onSelect: (question: string) => void;
  disabled?: boolean;
}

export function AgentDebugSuggestions({
  questions,
  onSelect,
  disabled,
}: AgentDebugSuggestionsProps) {
  const visibleQuestions = questions?.filter((question) => question.trim());
  if (!visibleQuestions?.length) return null;
  return (
    <section data-testid="agent-debug-suggestions">
      <TextSuggestion
        suggestions={visibleQuestions.map((question, index) => ({
          id: String(index),
          title: question,
          prompt: question,
        }))}
        disabled={disabled}
        onSelect={(prompt) => onSelect(prompt)}
      />
    </section>
  );
}
