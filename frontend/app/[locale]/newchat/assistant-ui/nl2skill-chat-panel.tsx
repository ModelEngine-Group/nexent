"use client";

import { useMemo, type FC } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { useTranslation } from "react-i18next";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import type { SkillFileContent } from "@/types/skill";
import { useConfig } from "@/hooks/useConfig";
import {
  remoteChatModelAdapter,
  type Nl2SkillStreamEvent,
} from "../adapter/remote-chat-model-adapter";
import { Chat } from "./chat";

interface Nl2SkillChatPanelProps {
  getDraftSnapshot: () => Record<string, unknown>;
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

export const Nl2SkillChatPanel: FC<Nl2SkillChatPanelProps> = ({
  getDraftSnapshot,
  onStreamEvent,
  language,
  availableFiles,
  onSkillFileSelect,
}) => {
  const { t } = useTranslation("common");
  // Get the current tenant's configured LLM model ID for NL2Skill
  const { defaultLlmModelConfig } = useConfig();
  const modelId = defaultLlmModelConfig?.id;

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      run(options) {
        return remoteChatModelAdapter.run({
          ...options,
          runConfig: {
            custom: {
              ...options.runConfig?.custom,
              runtimeMode: "nl2skill",
              draftSnapshot: getDraftSnapshot(),
              complexity: "complicated",
              language,
              onNl2SkillEvent: onStreamEvent,
              modelId,
            },
          },
        });
      },
    }),
    [getDraftSnapshot, language, onStreamEvent, modelId]
  );
  const runtime = useLocalRuntime(adapter);
  const assistantTitle = t("skillManagement.tabs.interactive");
  const displayAgent: Agent = {
    ...NL2SKILL_DISPLAY_BASE,
    display_name: assistantTitle,
    description: t("skillManagement.chat.createGreetingTitle"),
  };

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="h-full min-h-0 w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <Chat
            selectedAgent={displayAgent}
            generatedTitle={assistantTitle}
            welcomeTitle={t("skillManagement.chat.createWelcomeTitle")}
            isLoadingAgents={false}
            showModelSelector={false}
            variant="embedded"
            skillFiles={availableFiles}
            onSkillFileSelect={onSkillFileSelect}
          />
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
};
