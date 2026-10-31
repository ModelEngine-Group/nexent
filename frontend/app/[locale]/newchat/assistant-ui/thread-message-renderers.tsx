// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createContext,
  useContext,
  type ComponentType,
  type PropsWithChildren,
} from "react";
import type { Agent, PublishedAgent } from "@/types/agentConfig";

interface UserRenderProps {
  readOnly?: boolean;
  enableSkillDirectives?: boolean;
}

interface AssistantRenderProps {
  agent: Agent | PublishedAgent;
  showAgentCreationResult?: boolean;
  readOnly?: boolean;
  onSkillFileSelect?: (path: string) => void;
}

interface MessageRenderState extends AssistantRenderProps {
  enableSkillDirectives?: boolean;
  UserMessage: ComponentType<UserRenderProps>;
  AssistantMessage: ComponentType<AssistantRenderProps>;
}

const MessageRenderContext = createContext<MessageRenderState | null>(null);

export function ThreadMessageRenderProvider({
  children,
  ...value
}: PropsWithChildren<MessageRenderState>) {
  return (
    <MessageRenderContext.Provider value={value}>
      {children}
    </MessageRenderContext.Provider>
  );
}

function useMessageRenderState() {
  const state = useContext(MessageRenderContext);
  if (!state) throw new Error("Thread message renderer provider is missing");
  return state;
}

function StableUserMessage() {
  const { UserMessage, readOnly, enableSkillDirectives } =
    useMessageRenderState();
  return (
    <UserMessage
      readOnly={readOnly}
      enableSkillDirectives={enableSkillDirectives}
    />
  );
}

function StableAssistantMessage() {
  const {
    AssistantMessage,
    agent,
    readOnly,
    onSkillFileSelect,
    showAgentCreationResult,
  } = useMessageRenderState();
  return (
    <AssistantMessage
      agent={agent}
      showAgentCreationResult={showAgentCreationResult}
      readOnly={readOnly}
      onSkillFileSelect={onSkillFileSelect}
    />
  );
}

/** Component types remain stable while the provider delivers current render props. */
export const threadMessageRenderers = {
  UserMessage: StableUserMessage,
  AssistantMessage: StableAssistantMessage,
};
