import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useConfirmModal } from "../useConfirmModal";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { updateAgent, updateToolConfig } from "@/services/agentConfigService";
import { Agent } from "@/types/agentConfig";

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

      const result = await updateAgent(
        currentAgentId ?? undefined, // undefined = create，number = update
        currentEditedAgent.name,
        currentEditedAgent.description,
        currentEditedAgent.model,
        currentEditedAgent.max_step,
        currentEditedAgent.provide_run_summary,
        true, // enabled
        currentEditedAgent.business_description,
        currentEditedAgent.duty_prompt,
        currentEditedAgent.constraint_prompt,
        currentEditedAgent.few_shots_prompt,
        currentEditedAgent.display_name,
        currentEditedAgent.model_id ?? undefined,
        currentEditedAgent.business_logic_model_name ?? undefined,
        currentEditedAgent.business_logic_model_id ?? undefined,
        (currentEditedAgent.tools || [])
          .filter((tool: any) => tool && tool.is_available !== false)
          .map((tool: any) => Number(tool.id))
          .filter((id: number) => Number.isFinite(id)),
        (currentEditedAgent.sub_agent_id_list || [])
          .map((id: any) => Number(id))
          .filter((id: number) => Number.isFinite(id)),
        currentEditedAgent.author
      );

      if (result.success) {
        useAgentConfigStore.getState().markAsSaved(); // 标记为已保存
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
                console.error(`Failed to save tool config for tool ${toolId}:`, error);
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
        const updatedAgent = queryClient.getQueryData(["agentInfo", finalAgentId]) as Agent;
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
