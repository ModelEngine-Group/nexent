/**
 * Agent repository service for tenant marketplace listing API calls
 */

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  AgentRepositoryListingCreatePayload,
  AgentRepositoryListingDetail,
  AgentRepositoryListingItem,
  AgentRepositoryListingListParams,
  AgentRepositoryListingListResponse,
  AgentRepositoryListingStatus,
  MyEditableAgentListParams,
  MyEditableAgentListResponse,
  OfficialAgentGithubDiscoverResult,
  OfficialAgentInstallItem,
  OfficialAgentInstallOptions,
  OfficialAgentItem,
  RepositoryImportPrecheckResponse,
} from "@/types/agentRepository";

export async function fetchAgentRepositoryListings(
  params?: AgentRepositoryListingListParams
): Promise<AgentRepositoryListingListResponse> {
  try {
    const url = API_ENDPOINTS.agentRepository.listings(params);
    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch agent repository listings: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error fetching agent repository listings:", error);
    throw error;
  }
}

export async function fetchAgentRepositoryListingDetail(
  agentRepositoryId: number
): Promise<AgentRepositoryListingDetail> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.agentRepository.detail(agentRepositoryId),
      {
        method: "GET",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch agent repository listing detail: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error fetching agent repository listing detail:", error);
    throw error;
  }
}

export async function fetchMyEditableAgents(
  params?: MyEditableAgentListParams
): Promise<MyEditableAgentListResponse> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.agentRepository.mineAgents(params),
      {
        method: "GET",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to fetch my editable agents: ${response.statusText}`);
    }

    return response.json();
  } catch (error) {
    log.error("Error fetching my editable agents:", error);
    throw error;
  }
}

export async function createAgentRepositoryListing(
  agentId: number,
  versionNo: number,
  payload: AgentRepositoryListingCreatePayload
): Promise<AgentRepositoryListingDetail> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.agentRepository.createListing(agentId, versionNo),
      {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to create agent repository listing: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error creating agent repository listing:", error);
    throw error;
  }
}

export async function updateAgentRepositoryStatus(
  agentRepositoryId: number,
  status: AgentRepositoryListingStatus,
  content?: string
): Promise<AgentRepositoryListingItem> {
  try {
    const trimmedContent = content?.trim();
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.agentRepository.updateStatus(agentRepositoryId),
      {
        method: "PATCH",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          status,
          ...(trimmedContent ? { content: trimmedContent } : {}),
        }),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to update agent repository status: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error updating agent repository status:", error);
    throw error;
  }
}

export async function fetchRepositoryImportPrecheck(
  agentRepositoryId: number
): Promise<RepositoryImportPrecheckResponse> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.agentRepository.importPrecheck(agentRepositoryId),
      {
        method: "GET",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch repository import precheck: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error fetching repository import precheck:", error);
    throw error;
  }
}

export async function importAgentFromRepository(
  agentRepositoryId: number
): Promise<void> {
  try {
    const response = await fetch(
      API_ENDPOINTS.agentRepository.import(agentRepositoryId),
      {
        method: "POST",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const detail = errorData?.detail;
      const error = new Error(
        typeof detail === "string"
          ? detail
          : `Failed to import agent from repository: ${response.statusText}`
      ) as Error & { status?: number; detail?: unknown };
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
  } catch (error) {
    if (error instanceof Error && "status" in error) {
      throw error;
    }
    log.error("Error importing agent from repository:", error);
    throw error;
  }
}

export async function fetchOfficialAgentsWithStatus(
  tenantId?: string
): Promise<OfficialAgentItem[]> {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.agentRepository.official}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.agentRepository.official;
    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch official agents: ${response.statusText}`
      );
    }

    const data = await response.json();
    return data.agents ?? [];
  } catch (error) {
    log.error("Error fetching official agents:", error);
    throw error;
  }
}

export async function installOfficialAgents(
  agentNames: string[],
  options?: OfficialAgentInstallOptions,
  tenantId?: string
): Promise<OfficialAgentInstallItem[]> {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.agentRepository.officialInstall}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.agentRepository.officialInstall;
    const response = await fetchWithErrorHandling(url, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        agent_names: agentNames,
        ...(options?.renames ? { renames: options.renames } : {}),
        ...(options?.model_ids ? { model_ids: options.model_ids } : {}),
        ...(options?.embedding_model_ids
          ? { embedding_model_ids: options.embedding_model_ids }
          : {}),
        ...(options?.skill_renames
          ? { skill_renames: options.skill_renames }
          : {}),
        ...(options?.kb_renames ? { kb_renames: options.kb_renames } : {}),
        ...(options?.mcp_renames
          ? { mcp_renames: options.mcp_renames }
          : {}),
        ...(options?.mcp_skips ? { mcp_skips: options.mcp_skips } : {}),
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to install official agents: ${response.statusText}`
      );
    }

    const data = await response.json();
    return data.results ?? [];
  } catch (error) {
    log.error("Error installing official agents:", error);
    throw error;
  }
}

/** Discover the fixed GitCode AgentsHub repo into a grouped catalog. */
export async function fetchOfficialAgentsFromGitcode(
  tenantId?: string,
  ref?: string
): Promise<OfficialAgentGithubDiscoverResult> {
  const params = new URLSearchParams();
  if (tenantId) params.set("tenant_id", tenantId);
  if (ref) params.set("ref", ref);
  const query = params.toString();
  const url = query
    ? `${API_ENDPOINTS.agentRepository.officialGitcode}?${query}`
    : API_ENDPOINTS.agentRepository.officialGitcode;
  try {
    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch GitCode agents: ${response.statusText}`
      );
    }
    return (await response.json()) as OfficialAgentGithubDiscoverResult;
  } catch (error) {
    log.error("Error fetching GitCode agents:", error);
    throw error;
  }
}

/** Install remote official agents (from the fixed GitCode source) by bundle key. */
export async function installOfficialAgentsFromGitcode(
  agentNames: string[],
  options?: OfficialAgentInstallOptions,
  tenantId?: string
): Promise<OfficialAgentInstallItem[]> {
  const params = new URLSearchParams();
  if (tenantId) params.set("tenant_id", tenantId);
  const query = params.toString();
  const url = query
    ? `${API_ENDPOINTS.agentRepository.officialGitcodeInstall}?${query}`
    : API_ENDPOINTS.agentRepository.officialGitcodeInstall;
  try {
    const response = await fetchWithErrorHandling(url, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        agent_names: agentNames,
        ...(options?.renames ? { renames: options.renames } : {}),
        ...(options?.model_ids ? { model_ids: options.model_ids } : {}),
        ...(options?.embedding_model_ids
          ? { embedding_model_ids: options.embedding_model_ids }
          : {}),
        ...(options?.skill_renames
          ? { skill_renames: options.skill_renames }
          : {}),
        ...(options?.kb_renames ? { kb_renames: options.kb_renames } : {}),
        ...(options?.mcp_renames
          ? { mcp_renames: options.mcp_renames }
          : {}),
        ...(options?.mcp_skips ? { mcp_skips: options.mcp_skips } : {}),
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to install GitCode agents: ${response.statusText}`
      );
    }

    const data = await response.json();
    return data.results ?? [];
  } catch (error) {
    log.error("Error installing GitCode agents:", error);
    throw error;
  }
}

const agentRepositoryService = {
  fetchAgentRepositoryListings,
  fetchAgentRepositoryListingDetail,
  fetchMyEditableAgents,
  createAgentRepositoryListing,
  updateAgentRepositoryStatus,
  fetchRepositoryImportPrecheck,
  importAgentFromRepository,
  fetchOfficialAgentsWithStatus,
  installOfficialAgents,
  fetchOfficialAgentsFromGitcode,
  installOfficialAgentsFromGitcode,
};

export default agentRepositoryService;
