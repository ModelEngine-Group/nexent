import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { useConfirmModal } from "../useConfirmModal";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { updateAgent } from "@/services/agentConfigService";
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

        // For both creation and update, ensure the store has the latest agent data
        if (!currentAgentId && result.data?.agent_id) {
          // New agent creation - create agent object with backend-generated ID
          const newAgentId = result.data.agent_id.toString();
          const updatedAgent: Agent = {
            id: newAgentId, // Backend-generated ID as string
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
          };
          useAgentConfigStore.getState().setCurrentAgent(updatedAgent);
        } else if (currentAgentId) {
          // Existing agent update - invalidate and refetch the specific agent info cache
          await queryClient.invalidateQueries({
            queryKey: ["agentInfo", currentAgentId]
          });
          await queryClient.refetchQueries({
            queryKey: ["agentInfo", currentAgentId]
          });
          // Get the updated agent data from the refreshed cache
          const updatedAgent = queryClient.getQueryData(["agentInfo", currentAgentId]) as Agent;
          if (updatedAgent) {
            useAgentConfigStore.getState().setCurrentAgent(updatedAgent);
          }
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
