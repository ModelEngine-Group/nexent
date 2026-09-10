import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";

export interface AgentShareLink {
  agent_id: number;
  share_token: string;
  generation: number;
  status: "active";
}

async function readShareResponse(
  response: Response
): Promise<AgentShareLink | null> {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "Unable to manage Agent sharing.");
  }
  return response.json();
}

export const agentShareService = {
  async get(agentId: number): Promise<AgentShareLink | null> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.agent.share(agentId)
    );
    if (response.status === 404) {
      return null;
    }
    return readShareResponse(response);
  },

  async enable(agentId: number): Promise<AgentShareLink> {
    const share = await readShareResponse(
      await fetchWithErrorHandling(API_ENDPOINTS.agent.share(agentId), {
        method: "POST",
      })
    );
    if (!share) throw new Error("Unable to enable Agent sharing.");
    return share;
  },

  async rotate(agentId: number): Promise<AgentShareLink> {
    const share = await readShareResponse(
      await fetchWithErrorHandling(API_ENDPOINTS.agent.shareRotate(agentId), {
        method: "POST",
      })
    );
    if (!share) throw new Error("Unable to rotate Agent sharing.");
    return share;
  },

  async revoke(agentId: number): Promise<void> {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.agent.share(agentId),
      {
        method: "DELETE",
      }
    );
    if (!response.ok && response.status !== 404) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "Unable to disable Agent sharing.");
    }
  },
};
