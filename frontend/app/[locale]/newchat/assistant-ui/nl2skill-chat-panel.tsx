"use client";

import { useMemo, useEffect, useState, type FC } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { NexusAgent, type NexusRunConfig } from "@/lib/assistant-ui/nexus-agent";
import { useTranslation } from "react-i18next";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import type { SkillFileContent } from "@/types/skill";
import { useConfig } from "@/hooks/useConfig";
import { Chat } from "./chat";
import { getAuthHeaders } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";

// Register nl2skill endpoint URL with NexusAgent
NexusAgent.registerEndpoint("nl2skill", API_ENDPOINTS.skills.nl2skillRun);

interface Nl2SkillChatPanelProps {
  getDraftSnapshot: () => Record<string, unknown>;
  onStreamEvent: (event: unknown) => void;
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
  const { defaultLlmModelConfig } = useConfig();
  const modelId = defaultLlmModelConfig?.id;

  // ---- NexusAgent: memoized with nl2skill endpoint ------------------------
  const nexusAgent = useMemo(
    () =>
      new NexusAgent({
        url: API_ENDPOINTS.skills.nl2skillRun,
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
          "x-agui-format": "true",
        },
      }),
    []
  );

  // ---- runConfig ----------------------------------------------------------
  const [runConfig, setRunConfig] = useState<NexusRunConfig>({
    runtime_mode: "nl2skill",
    model_id: modelId,
    complexity: "complicated",
    language,
  });

  useEffect(() => {
    nexusAgent.setRunConfig({
      runtime_mode: "nl2skill",
      model_id: modelId,
      complexity: "complicated",
      language,
      draft_snapshot: getDraftSnapshot(),
    });
  }, [nexusAgent, modelId, language, getDraftSnapshot]);

  // ---- useAgUiRuntime -----------------------------------------------------
  const runtime = useAgUiRuntime({
    agent: nexusAgent,
    showThinking: true,
    onError: (e) => console.error("[NL2Skill] AG-UI runtime error:", e),
  });

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
