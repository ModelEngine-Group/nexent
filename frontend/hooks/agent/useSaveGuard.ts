import { useCallback } from "react";
import { App } from "antd";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { checkAgentNameConflictBatch } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";

const AGENT_NAME_PATTERN = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

export const AGENT_NAME_MAX_LENGTH = 60;
export const AGENT_DESCRIPTION_MAX_LENGTH = 500;

export const isValidAgentName = (name: string): boolean =>
  name.length <= AGENT_NAME_MAX_LENGTH && AGENT_NAME_PATTERN.test(name);

export const isValidAgentDisplayName = (name: string): boolean =>
  name.length <= AGENT_NAME_MAX_LENGTH;

export const isValidAgentDescription = (description: string): boolean =>
  description.length <= AGENT_DESCRIPTION_MAX_LENGTH;

type AgentNameField = "name" | "display_name";

type AgentNameConflictStatus =
  | "available"
  | "name_duplicate"
  | "display_name_duplicate"
  | "check_failed";

export async function checkAgentNameConflict(
  field: AgentNameField,
  value: string | undefined,
  agentId?: number
): Promise<AgentNameConflictStatus> {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) return "available";

  const result = await checkAgentNameConflictBatch({
    items: [
      {
        [field]: trimmed,
        agent_id: agentId,
      },
    ],
  });
  if (!result.success || !Array.isArray(result.data)) {
    return "check_failed";
  }

  const conflict = result.data[0];
  if (conflict?.name_conflict) return "name_duplicate";
  if (conflict?.display_name_conflict) return "display_name_duplicate";
  return "available";
}

export const createAgentNameConflictValidator = (
  t: TFunction,
  field: AgentNameField,
  agentId?: number
) => ({
  async validator(_: unknown, value: string) {
    const status = await checkAgentNameConflict(field, value, agentId);
    if (status === "available") return Promise.resolve();

    const messageKey =
      status === "name_duplicate"
        ? "agent.validation.nameDuplicate"
        : status === "display_name_duplicate"
          ? "agent.validation.displayNameDuplicate"
          : field === "name"
            ? "agent.validation.nameConflictCheckFailed"
            : "agent.validation.displayNameConflictCheckFailed";
    return Promise.reject(new Error(t(messageKey)));
  },
});

/**
 * Waits for automatic draft persistence after validating the current agent.
 */
export const useSaveGuard = () => {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const validateCurrentAgent = useCallback(async (): Promise<boolean> => {
    const { agentId, editedAgent } = useAgentStore.getState();
    if (!editedAgent || agentId === null) return false;

    const name = (editedAgent.name ?? "").trim();
    const displayName = (editedAgent.display_name ?? "").trim();
    const description = (editedAgent.description ?? "").trim();

    if (!displayName) {
      message.error(t("agent.validation.displayNameRequired"));
      return false;
    }
    if (!isValidAgentDisplayName(displayName)) {
      message.error(
        t("agent.validation.displayNameMaxLength", {
          max: AGENT_NAME_MAX_LENGTH,
        })
      );
      return false;
    }
    if (!name) {
      message.error(t("agent.validation.nameRequired"));
      return false;
    }
    if (!isValidAgentName(name)) {
      message.error(t("agent.validation.namePattern"));
      return false;
    }
    if (!description) {
      message.error(t("agent.validation.descriptionRequired"));
      return false;
    }
    if (!isValidAgentDescription(description)) {
      message.error(
        t("agent.validation.descriptionMaxLength", {
          max: AGENT_DESCRIPTION_MAX_LENGTH,
        })
      );
      return false;
    }
    if (!editedAgent.model_ids?.length) {
      message.error(t("agent.validation.modelRequired"));
      return false;
    }

    const nameStatus = await checkAgentNameConflict("name", name, agentId);
    if (nameStatus !== "available") {
      message.error(
        t(
          nameStatus === "name_duplicate"
            ? "agent.validation.nameDuplicate"
            : "agent.validation.nameConflictCheckFailed"
        )
      );
      return false;
    }

    const displayNameStatus = await checkAgentNameConflict(
      "display_name",
      displayName,
      agentId
    );
    if (displayNameStatus !== "available") {
      message.error(
        t(
          displayNameStatus === "display_name_duplicate"
            ? "agent.validation.displayNameDuplicate"
            : "agent.validation.displayNameConflictCheckFailed"
        )
      );
      return false;
    }

    return true;
  }, [message, t]);

  const save = useCallback(async (): Promise<boolean> => {
    const store = useAgentStore.getState();
    store.flushDraft();
    if (!(await store.waitForIdle())) {
      message.error(t("businessLogic.config.error.saveFailed"));
      return false;
    }

    return validateCurrentAgent();

  }, [message, t, validateCurrentAgent]);

  return { save, saveWithModal: save };
};
