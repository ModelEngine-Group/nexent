import {
  searchAgentInfo,
  updateAgentInfo,
} from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";

/** Create the editable AgentInfo record required by the existing NL2Agent runtime. */
export async function createWorkbenchAgentDraft(author: string) {
  const displayName = `Workbench Draft ${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const created = await updateAgentInfo({
    display_name: displayName,
    description: "",
    author,
    max_steps: 15,
    is_main_agent: true,
    provide_run_summary: false,
    enabled: true,
  });
  const agentId = Number(created.data?.agent_id);
  if (!created.success || !Number.isInteger(agentId) || agentId <= 0) {
    throw new Error(created.message || "Failed to create an Agent draft");
  }
  return { agentId, displayName };
}

/** NL2Agent resource cards reuse the Agent editor's draft and autosave store. */
export async function prepareWorkbenchAgentDraft(
  agentId: number
): Promise<void> {
  const result = await searchAgentInfo(agentId, undefined, 0);
  if (!result.success || !result.data) {
    throw new Error(result.message || "Failed to load the Agent draft");
  }
  useAgentStore.getState().initialize({ ...result.data, permission: "EDIT" });
}
