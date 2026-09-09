import { previewWorkbenchAgent } from "./api";
import { initialWorkbenchState, workbenchReducer } from "./state";
import { fetchSkillsList } from "@/services/skillService";
import type { WorkbenchSessionConfig } from "./types";
import type { ConversationKnowledgeScope } from "@/types/knowledgeScope";

/** Resolve display resources before releasing the conversation's send gate. */
export async function resolveRestoredWorkbench(conversation: {
  workbench_config?: WorkbenchSessionConfig | null;
  workbench_config_version?: number;
  agent_id?: number | string | null;
  knowledge_scope?: ConversationKnowledgeScope | null;
}) {
  let config = conversation.workbench_config;
  const version = config ? (conversation.workbench_config_version ?? 0) : 0;
  if (config) {
    await Promise.all(
      config.agent_mounts.map((mount) =>
        previewWorkbenchAgent(mount.agent_id, mount.version_no)
      )
    );
  } else if (conversation.agent_id != null) {
    const preview = await previewWorkbenchAgent(Number(conversation.agent_id));
    config = workbenchReducer(initialWorkbenchState, {
      type: "resolve-agent-success",
      preview,
    }).config;
  } else {
    config = structuredClone(initialWorkbenchState.config);
  }
  if (!conversation.workbench_config)
    config = {
      ...config,
      knowledge_scope: conversation.knowledge_scope ?? undefined,
    };
  const skillNames: Record<number, string> = {};
  if (config.skill_mounts.length) {
    const skills = await fetchSkillsList();
    for (const mount of config.skill_mounts) {
      const skill = skills.find(
        (item) => Number(item.skill_id) === mount.skill_id
      );
      if (!skill) throw new Error("会话中有不可用的 Skill，请检查资源权限");
      skillNames[mount.skill_id] = skill.name;
    }
  }
  return { config, version, skillNames };
}
