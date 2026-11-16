// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { t as translate } from "i18next";
import { getCreatorMode } from "@/lib/creatorConversation";
import { initialWorkbenchState } from "./state";
import { previewWorkbenchAgent } from "./api";
import { fetchSkillById } from "@/services/agentConfigService";
import type { WorkbenchSessionConfig } from "./types";
import type { ConversationKnowledgeScope } from "@/types/knowledgeScope";

/** Validate only saved mounts before releasing the conversation send gate. */
export async function resolveRestoredWorkbench(conversation: {
  workbench_config?: WorkbenchSessionConfig | null;
  workbench_config_version?: number;
  agent_id?: number | string | null;
  agent_system_key?: string | null;
  knowledge_scope?: ConversationKnowledgeScope | null;
}) {
  const mode = getCreatorMode(conversation);
  // A standalone creator gets transient display state; never persist it as Workbench configuration.
  const config =
    conversation.workbench_config ??
    (mode
      ? { ...structuredClone(initialWorkbenchState.config), mode }
      : undefined);
  if (!config)
    throw new Error("This conversation does not belong to Workbench");
  const version = conversation.workbench_config_version ?? 0;
  const skillNames: Record<number, string> = {};
  await Promise.all([
    ...config.agent_mounts.map((mount) =>
      previewWorkbenchAgent(mount.agent_id, mount.version_no)
    ),
    ...config.skill_mounts.map(async (mount) => {
      const result = await fetchSkillById(mount.skill_id);
      if (!result.success || !result.data)
        throw new Error(
          translate("ui.localization.conversationSkillsUnavailable")
        );
      skillNames[mount.skill_id] = result.data.name || `#${mount.skill_id}`;
    }),
  ]);
  return { config, version, skillNames };
}
