import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useConfirmModal } from "../useConfirmModal";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { updateAgentInfo, updateToolConfig } from "@/services/agentConfigService";
import { Agent } from "@/types/agentConfig";
import log from "@/lib/logger";

/**
 * Hook for handling agent save guard logic
 * Provides two functions: one with confirmation dialog, one for direct save
 *
 * This hook encapsulates the complete flow of checking for unsaved changes
 * and handling the save/discard decision for agent configurations.
 *
 * @returns object with promptSaveGuard and saveDirectly functions
 */
export const useSaveGuard = () => {
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  // Shared save logic
  const save = useCallback(async (): Promise<boolean> => {
    try {
      const currentEditedAgent = useAgentConfigStore.getState().editedAgent;
      const currentAgentId = useAgentConfigStore.getState().currentAgentId;

      // Validate required fields
      if (!currentEditedAgent.name.trim()) {
        message.error(t("agent.validation.nameRequired"));
        return false;
      }

      const enabledToolIds = (currentEditedAgent.tools || [])
        .filter((tool: any) => tool && tool.is_available !== false)
        .map((tool: any) => Number(tool.id))
        .filter((id: number) => Number.isFinite(id));

      const relatedAgentIds = (currentEditedAgent.sub_agent_id_list || [])
        .map((id: any) => Number(id))
        .filter((id: number) => Number.isFinite(id));

      const groupIds = (currentEditedAgent.group_ids || [])
        .map((id: any) => Number(id))
        .filter((id: number) => Number.isFinite(id));

      const result = await updateAgentInfo({
        agent_id: currentAgentId ?? undefined, // undefined=create, number=update
        name: currentEditedAgent.name,
        display_name: currentEditedAgent.display_name,
        description: currentEditedAgent.description,
        author: currentEditedAgent.author,
        group_ids: groupIds,
        model_name: currentEditedAgent.model,
        model_id: currentEditedAgent.model_id ?? undefined,
        max_steps: currentEditedAgent.max_step,
        provide_run_summary: currentEditedAgent.provide_run_summary,
        enabled: true,
        business_description: currentEditedAgent.business_description,
        duty_prompt: currentEditedAgent.duty_prompt,
        constraint_prompt: currentEditedAgent.constraint_prompt,
        few_shots_prompt: currentEditedAgent.few_shots_prompt,
        business_logic_model_name: currentEditedAgent.business_logic_model_name ?? undefined,
        business_logic_model_id: currentEditedAgent.business_logic_model_id ?? undefined,
        enabled_tool_ids: enabledToolIds,
        related_agent_ids: relatedAgentIds,
      });

      if (result.success) {
        useAgentConfigStore.getState().markAsSaved(); // Mark as saved
        message.success(
            t("businessLogic.config.message.agentSaveSuccess")
        );

        // Get the final agent ID (from result for new agents, existing currentAgentId for updates)
        const finalAgentId = result.data?.agent_id || currentAgentId;
        if (!finalAgentId) {
          throw new Error("Failed to get agent ID after save operation");
        }

        // Handle new agent creation - save tool configurations
        if (!currentAgentId && result.data?.agent_id) {
          // Save tool configurations for the newly created agent
          const agentIdNumber = result.data.agent_id;
          if (currentEditedAgent.tools && currentEditedAgent.tools.length > 0) {
            for (const tool of currentEditedAgent.tools) {
              const toolId = parseInt(tool.id);
              const isEnabled = tool.is_available !== false; // Default to true if not explicitly set to false
              const params = tool.initParams?.reduce((acc, param) => {
                acc[param.name] = param.value;
                return acc;
              }, {} as Record<string, any>) || {};

              try {
                await updateToolConfig(toolId, agentIdNumber, params, isEnabled);
              } catch (error) {
                log.error(`Failed to save tool config for tool ${toolId}:`, error);
                // Continue with other tools even if one fails
              }
            }
          }
        }

        // Common logic for both creation and update: refresh cache and update store
        await queryClient.invalidateQueries({
          queryKey: ["agentInfo", finalAgentId]
        });
        await queryClient.refetchQueries({
          queryKey: ["agentInfo", finalAgentId]
        });
        // Get the updated agent data from the refreshed cache
        let updatedAgent = queryClient.getQueryData(["agentInfo", finalAgentId]) as Agent;

        // For new agents, the cache might not be populated yet
        // Construct a minimal Agent object from the edited data
        if (!updatedAgent && finalAgentId) {
          updatedAgent = {
            id: String(finalAgentId),
            name: currentEditedAgent.name,
            display_name: currentEditedAgent.display_name,
            description: currentEditedAgent.description,
            author: currentEditedAgent.author,
            model: currentEditedAgent.model,
            model_id: currentEditedAgent.model_id,
            max_step: currentEditedAgent.max_step,
            provide_run_summary: currentEditedAgent.provide_run_summary,
            tools: currentEditedAgent.tools || [],
            duty_prompt: currentEditedAgent.duty_prompt,
            constraint_prompt: currentEditedAgent.constraint_prompt,
            few_shots_prompt: currentEditedAgent.few_shots_prompt,
            business_description: currentEditedAgent.business_description,
            business_logic_model_name: currentEditedAgent.business_logic_model_name,
            business_logic_model_id: currentEditedAgent.business_logic_model_id,
            sub_agent_id_list: currentEditedAgent.sub_agent_id_list,
            group_ids: currentEditedAgent.group_ids || [],
          };
        }

        if (updatedAgent) {
          useAgentConfigStore.getState().setCurrentAgent(updatedAgent);
        }

        // Also invalidate the agents list cache to ensure the list reflects any changes
        queryClient.invalidateQueries({ queryKey: ["agents"] });

        return true;
      } else {
        message.error(result.message || t("businessLogic.config.error.saveFailed") );
        return false;
      }
    } catch (error) {
      message.error(t("businessLogic.config.error.saveFailed") );
      return false;
    }
  }, [t, message, queryClient]);

  // Function with confirmation dialog - prompts user to save/discard
  const saveWithModal = useCallback(
    async (): Promise<boolean> => {
      // Get the latest hasUnsavedChanges from store at call time
      const currentHasUnsavedChanges = useAgentConfigStore.getState().hasUnsavedChanges;

      if (!currentHasUnsavedChanges) {
        return true; // No unsaved changes, proceed
      }

      // Show confirmation dialog
      return new Promise((resolve) => {
        confirm({
          title: t("agentConfig.modals.saveConfirm.title"),
          content: t("agentConfig.modals.saveConfirm.content"),
          okText: t("agentConfig.modals.saveConfirm.save"),
          cancelText: t("agentConfig.modals.saveConfirm.discard"),
          onOk: async () => {
            const success = await save();
            resolve(success);
          },
          onCancel: () => {
            // Discard changes
            useAgentConfigStore.getState().discardChanges();
            resolve(true);
          },
        });
      });
    },
    []
  );

  // Function for direct save - saves without confirmation dialog
  const saveDirectly = useCallback(
    async (): Promise<boolean> => {
      // Get the latest hasUnsavedChanges from store at call time
      const currentHasUnsavedChanges = useAgentConfigStore.getState().hasUnsavedChanges;

      if (!currentHasUnsavedChanges) {
        return true; // No unsaved changes, nothing to save
      }

      // Save directly without confirmation
      return await save();
    },
    []
  );

  return { save, saveWithModal };
};
