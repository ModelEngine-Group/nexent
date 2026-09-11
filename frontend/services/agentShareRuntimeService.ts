import { getAuthHeaders, fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";

export interface AgentShareMetadata {
  display_name: string;
  description: string;
  icon_url: string | null;
  greeting_message: string;
  session_recoverable: boolean;
}

export interface AgentShareHistoryResponse {
  history: unknown;
  session_recoverable: boolean;
}

export interface AgentShareSession {
  agent_version_no: number;
  session_recoverable: true;
}

async function readJson<T>(response: Response): Promise<T> {
  return response.json() as Promise<T>;
}

export const agentShareRuntimeService = {
  async getMetadata(shareToken: string): Promise<AgentShareMetadata> {
    return readJson(
      await fetchWithAuth(API_ENDPOINTS.agentShare.metadata(shareToken))
    );
  },

  async getHistory(shareToken: string): Promise<AgentShareHistoryResponse> {
    return readJson(
      await fetchWithAuth(API_ENDPOINTS.agentShare.history(shareToken))
    );
  },

  async createOrRestoreSession(shareToken: string): Promise<AgentShareSession> {
    return readJson(
      await fetchWithAuth(API_ENDPOINTS.agentShare.session(shareToken), {
        method: "POST",
      })
    );
  },

  async run(
    shareToken: string,
    payload: { query: string; timezone?: string },
    signal?: AbortSignal
  ): Promise<ReadableStreamDefaultReader<Uint8Array>> {
    const response = await fetchWithAuth(
      API_ENDPOINTS.agentShare.run(shareToken),
      {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
        signal,
      }
    );
    if (!response.body)
      throw new Error("The Agent did not return a response stream.");
    return response.body.getReader();
  },

  async stop(shareToken: string): Promise<void> {
    await fetchWithAuth(API_ENDPOINTS.agentShare.stop(shareToken), {
      method: "POST",
    });
  },
};
