import { API_ENDPOINTS, ApiError } from "./api";
import { fetchWithAuth, getAuthHeaders } from "@/lib/auth";
import type {
  AgentAutomationRun,
  AgentAutomationProposalData,
  AgentAutomationTask,
  UpdateAutomationTaskPayload,
} from "@/types/agentAutomation";

const fetch = fetchWithAuth;

async function readResponse<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (response.ok && data.code === 0) {
    return data.data;
  }
  const detail =
    data.detail || (typeof data.message === "object" ? data.message : {});
  throw new ApiError(
    detail.code ?? data.code ?? response.status,
    detail.message ??
      (typeof data.message === "string" ? data.message : response.statusText)
  );
}

export const agentAutomationService = {
  async list(status?: string): Promise<AgentAutomationTask[]> {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
    const response = await fetch(
      `${API_ENDPOINTS.agentAutomation.list}${suffix}`,
      {
        headers: getAuthHeaders(),
      }
    );
    return readResponse<AgentAutomationTask[]>(response);
  },

  async update(
    taskId: number,
    payload: UpdateAutomationTaskPayload
  ): Promise<AgentAutomationTask> {
    const response = await fetch(API_ENDPOINTS.agentAutomation.update(taskId), {
      method: "PATCH",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    return readResponse<AgentAutomationTask>(response);
  },

  async pause(taskId: number): Promise<AgentAutomationTask> {
    const response = await fetch(API_ENDPOINTS.agentAutomation.pause(taskId), {
      method: "POST",
      headers: getAuthHeaders(),
    });
    return readResponse<AgentAutomationTask>(response);
  },

  async resume(taskId: number): Promise<AgentAutomationTask> {
    const response = await fetch(API_ENDPOINTS.agentAutomation.resume(taskId), {
      method: "POST",
      headers: getAuthHeaders(),
    });
    return readResponse<AgentAutomationTask>(response);
  },

  async run(taskId: number): Promise<AgentAutomationRun> {
    const response = await fetch(API_ENDPOINTS.agentAutomation.run(taskId), {
      method: "POST",
      headers: getAuthHeaders(),
    });
    return readResponse<AgentAutomationRun>(response);
  },

  async delete(taskId: number): Promise<boolean> {
    const response = await fetch(API_ENDPOINTS.agentAutomation.delete(taskId), {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    return readResponse<boolean>(response);
  },

  async runs(taskId: number): Promise<AgentAutomationRun[]> {
    const response = await fetch(API_ENDPOINTS.agentAutomation.runs(taskId), {
      headers: getAuthHeaders(),
    });
    return readResponse<AgentAutomationRun[]>(response);
  },

  async cancelRun(runId: number): Promise<AgentAutomationRun> {
    const response = await fetch(
      API_ENDPOINTS.agentAutomation.cancelRun(runId),
      {
        method: "POST",
        headers: getAuthHeaders(),
      }
    );
    return readResponse<AgentAutomationRun>(response);
  },

  async createProposal(payload: {
    conversation_id?: number;
    agent_id: number;
    message: string;
    timezone?: string;
    agent_version_no?: number | null;
    model_id?: number | null;
    tool_params?: Record<string, unknown> | null;
  }): Promise<AgentAutomationProposalData> {
    const response = await fetch(API_ENDPOINTS.agentAutomation.proposals, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    return readResponse<AgentAutomationProposalData>(response);
  },

  async confirmProposal(
    proposalId: number,
    payload?: { instruction?: string }
  ): Promise<AgentAutomationTask> {
    const response = await fetch(
      API_ENDPOINTS.agentAutomation.confirmProposal(proposalId),
      {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(payload || {}),
      }
    );
    return readResponse<AgentAutomationTask>(response);
  },

  async getByConversation(
    conversationId: number
  ): Promise<AgentAutomationTask | null> {
    const response = await fetch(
      API_ENDPOINTS.agentAutomation.conversation(conversationId),
      {
        headers: getAuthHeaders(),
      }
    );
    return readResponse<AgentAutomationTask | null>(response);
  },
};
