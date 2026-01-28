import { clearAgentNewMark } from "@/services/agentConfigService";
import type { QueryClient } from "@tanstack/react-query";

export async function clearAgentAndSync(agentId: string | number, queryClient: QueryClient) {
  try {
    const res = await clearAgentNewMark(agentId);
    if (res?.success) {
      // invalidate agents so all components refetch
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      // broadcast to other tabs
      try {
        const bc = new BroadcastChannel("nexent-agent-updates");
        bc.postMessage({ type: "agents_updated", agent_id: Number(agentId), timestamp: Date.now() });
        bc.close();
      } catch (e) {
        // BroadcastChannel may not be available in all envs; ignore errors
      }
      return { success: true, data: res.data };
    } else {
      return { success: false, data: res?.data, message: res?.message || "Failed to clear NEW mark" };
    }
  } catch (error) {
    return { success: false, error };
  }
}


