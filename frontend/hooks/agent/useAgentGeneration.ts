/**
 * useAgentGeneration hook
 *
 * Handles the agent generation flow:
 * - Validation (business description, model selection)
 * - Call generatePromptStream service
 * - Cache each stream chunk to localStorage
 * - Call onStreamUpdate callback to update form in real-time
 * - On completion: read cache, update store, clear cache
 * - On error: clear cache, report error
 */

import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import log from "@/lib/logger";
import {
  getAgentGenerationCache,
  setAgentGenerationStatus,
  saveGeneratedField,
  clearAgentGenerationCache,
} from "@/lib/agentGenerationCache";
import { generatePromptStream } from "@/services/promptService";
import { GENERATE_PROMPT_STREAM_TYPES } from "@/const/agentConfig";

// Re-export the stream types for use in the component
export { GENERATE_PROMPT_STREAM_TYPES };
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { AgentConfigUpdate } from "@/types/agentConfig";

export interface StreamUpdatePayload {
  type: typeof GENERATE_PROMPT_STREAM_TYPES[keyof typeof GENERATE_PROMPT_STREAM_TYPES];
  content: string;
}

export interface UseAgentGenerationProps {
  setActiveTab: (tab: string) => void;
  onStreamUpdate?: (payload: StreamUpdatePayload) => void;
}

export interface UseAgentGenerationReturn {
  handleGenerateAgent: () => Promise<void>;
  loadCachedGeneration: (agentId: number) => ReturnType<typeof getAgentGenerationCache>;
}

export function useAgentGeneration({
  setActiveTab,
  onStreamUpdate,
}: UseAgentGenerationProps): UseAgentGenerationReturn {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  
  // Read state directly from store
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const updateAgentConfig = useAgentConfigStore((state) => state.updateAgentConfig);
  const setIsGenerating = useAgentConfigStore((state) => state.setIsGenerating);
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode)

  // Derive businessInfo from editedAgent
  const businessInfo = {
    businessDescription: editedAgent.business_description,
    businessLogicModelId: editedAgent.business_logic_model_id,
    businessLogicModelName: editedAgent.business_logic_model_name,
    promptTemplateId: editedAgent.prompt_template_id,
    promptTemplateName: editedAgent.prompt_template_name,
  };

  const handleGenerateAgent = useCallback(async () => {
    // Validate business description
    if (!businessInfo.businessDescription || businessInfo.businessDescription.trim() === "") {
      message.error(t("businessLogic.config.error.businessDescriptionRequired"));
      return;
    }

    // Validate model selection
    if (!businessInfo.businessLogicModelId) {
      message.error("Please select a model first");
      return;
    }

    // In create mode, effectiveAgentId = 0
    const effectiveAgentId = currentAgentId ?? 0;

    setIsGenerating(true);
    setActiveTab("few-shots");

    // Mark generation as in progress in cache
    setAgentGenerationStatus(effectiveAgentId, true);

    // Extract knowledge base display names from selected tools
    const knowledgeBaseDisplayNames: string[] = [];
    if (Array.isArray(editedAgent.tools)) {
      for (const tool of editedAgent.tools) {
        if (typeof tool === "object" && tool.display_names && Array.isArray(tool.display_names)) {
          knowledgeBaseDisplayNames.push(...tool.display_names);
        }
      }
    }

    try {
      await generatePromptStream(
        {
          agent_id: effectiveAgentId,
          task_description: businessInfo.businessDescription,
          model_id: businessInfo.businessLogicModelId,
          prompt_template_id: businessInfo.promptTemplateId,
          sub_agent_ids: editedAgent.sub_agent_id_list,
          tool_ids: Array.isArray(editedAgent.tools)
            ? editedAgent.tools.map((tool: any) =>
                typeof tool === "object" && tool.id !== undefined
                  ? tool.id
                  : tool
              )
            : [],
          knowledge_base_display_names: knowledgeBaseDisplayNames.length > 0 ? knowledgeBaseDisplayNames : undefined,
        },
        (data) => {
          const generationAgentId = effectiveAgentId;

          const liveCurrentAgentId = useAgentConfigStore.getState().currentAgentId;
          const isCurrentAgent = liveCurrentAgentId === null || liveCurrentAgentId === generationAgentId;

          if (isCurrentAgent) {
            onStreamUpdate?.({
              type: data.type,
              content: data.content,
            });
          }

          switch (data.type) {
            case GENERATE_PROMPT_STREAM_TYPES.DUTY:
              saveGeneratedField(generationAgentId, 'dutyPrompt', data.content);
              break;
            case GENERATE_PROMPT_STREAM_TYPES.CONSTRAINT:
              saveGeneratedField(generationAgentId, 'constraintPrompt', data.content);
              break;
            case GENERATE_PROMPT_STREAM_TYPES.FEW_SHOTS:
              saveGeneratedField(generationAgentId, 'fewShotsPrompt', data.content);
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_VAR_NAME:
              // Only save to cache if user hasn't filled in agent name themselves
              if (!editedAgent.name) {
                saveGeneratedField(generationAgentId, 'agentName', data.content);
              }
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DESCRIPTION:
              // Only save to cache if user hasn't filled in agent description themselves
              if (!editedAgent.description) {
                saveGeneratedField(generationAgentId, 'agentDescription', data.content);
              }
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DISPLAY_NAME:
              // Only save to cache if user hasn't filled in agent display name themselves
              if (!editedAgent.display_name) {
                saveGeneratedField(generationAgentId, 'agentDisplayName', data.content);
              }
              break;
          }
        },
        (error) => {
          log.error("Generate prompt stream error:", error);

          setIsGenerating(false);

          // Try to get i18n translated message using error code, fallback to backend message or default
          let errorMessage = t("businessLogic.config.message.generateError");
          if (error?.code) {
            const i18nKey = `errorCode.${error.code}`;
            const translated = t(i18nKey);
            if (translated !== i18nKey) {
              errorMessage = translated;
            } else if (error?.message) {
              errorMessage = error.message;
            }
          } else if (error?.message) {
            errorMessage = error.message;
          }
          message.error(errorMessage);

          // Clear cache for this agent
          setAgentGenerationStatus(effectiveAgentId, false);
        },
        () => {
          // Read cached values as primary source
          const generationAgentId = effectiveAgentId;
          const cached = getAgentGenerationCache(generationAgentId);

          // Use store.getState() to read the latest currentAgentId at execution time
          const liveCurrentAgentId = useAgentConfigStore.getState().currentAgentId;
          // Verify the user is still on the same agent to avoid updating wrong data
          if (liveCurrentAgentId !== null && liveCurrentAgentId !== generationAgentId) {
            // User has switched to another agent, keep the cache for later use
            // when they return to this agent
            log.info(
              `Agent generation completed for agent ${generationAgentId}, ` +
              `but user is on agent ${currentAgentId}. Keeping cache for later restoration.`
            );
            setIsGenerating(false);
            setAgentGenerationStatus(generationAgentId, false);
            message.warning(t("businessLogic.config.message.generateCompleteDifferentAgent"));
            return;
          }

          // User is still on the same agent, apply the generated content
          // AI-generated fields come from cache, other fields come from editedAgent
          const configUpdates: AgentConfigUpdate = {
            name: cached?.agentName || editedAgent.name || "",
            display_name: cached?.agentDisplayName || editedAgent.display_name || "",
            description: cached?.agentDescription || editedAgent.description || "",
            duty_prompt: cached?.dutyPrompt || editedAgent.duty_prompt || "",
            constraint_prompt: cached?.constraintPrompt || editedAgent.constraint_prompt || "",
            few_shots_prompt: cached?.fewShotsPrompt || editedAgent.few_shots_prompt || "",
          };
          // Update agent config in store
          updateAgentConfig(configUpdates);

          // Clear the cache since generation completed successfully
          clearAgentGenerationCache(generationAgentId);

          setIsGenerating(false);
          message.success(t("businessLogic.config.message.generateSuccess"));
        }
      );
    } catch (error) {
      log.error("Generate agent error:", error);
      message.error(t("businessLogic.config.message.generateError"));

      setIsGenerating(false);
      setAgentGenerationStatus(effectiveAgentId, false);
    }
  }, [
    editedAgent,
    updateAgentConfig,
    businessInfo,
    setIsGenerating,
    setActiveTab,
    onStreamUpdate,
    t,
    message,
  ]);

  const loadCachedGeneration = useCallback((agentId: number) => {
    return getAgentGenerationCache(agentId);
  }, []);

  return {
    handleGenerateAgent,
    loadCachedGeneration,
  };
}
