import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import type { WorkbenchBootstrap, WorkbenchCapabilityPreview } from "./types";

function unwrap<T>(payload: unknown): T {
  return (payload as { data: T }).data;
}

export async function fetchWorkbenchBootstrap(): Promise<WorkbenchBootstrap> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.agent.workbenchBootstrap,
    { headers: getAuthHeaders() }
  );
  return unwrap<WorkbenchBootstrap>(await response.json());
}

export async function previewWorkbenchAgent(
  agentId: number,
  versionNo?: number
): Promise<WorkbenchCapabilityPreview> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.agent.workbenchPreview,
    {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id: agentId, version_no: versionNo }),
    }
  );
  return unwrap<WorkbenchCapabilityPreview>(await response.json());
}
