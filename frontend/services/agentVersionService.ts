import { API_ENDPOINTS } from "./api";
import log from "@/lib/logger";
import { getAuthHeaders } from "@/lib/auth";

/**
 * Tool instance from API response
 */
export interface ToolInstance {
  tool_instance_id: number;
  tool_id: number;
  agent_id: number;
  params: Record<string, any>;
  user_id: string;
  tenant_id: string;
  enabled: boolean;
  version_no: number;
  delete_flag: string;
}

export interface Agent {
  agent_id: number;
  name: string;
  display_name?: string;
  description: string;
  author?: string;
  model_name?: string;
  model_id?: number;
  max_steps: number;
  duty_prompt?: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;
  parent_agent_id?: number;
  tenant_id: string;
  enabled: boolean;
  provide_run_summary: boolean;
  business_description?: string;
  business_logic_model_name?: string;
  business_logic_model_id?: number;
  group_ids?: number[];
  is_new?: boolean;
  version_no?: number;
  current_version_no?: number;
  sub_agent_id_list?: number[];
  is_available?: boolean;
  unavailable_reasons?: string[];
  tools: ToolInstance[];
}

export interface AgentVersion { 
  version_no: number;
  version_name: string;
  release_note: string;
  source_type: string;
  source_version_no: number;
  status: string;
  create_time: string;
  update_time: string;
}

export interface AgentVersionResponse {
  code: number;
  message: string;
  data: AgentVersion;
}

export interface FetchAgentVersionResult {
  success: boolean;
  data: AgentVersion;
  message: string;
}

/**
 * Agent version detail - extends Agent with version metadata
 */
export interface AgentVersionDetail extends Agent {
  version: AgentVersion;
}

export interface AgentVersionDetailResponse {
  code: number;
  message: string;
  data: AgentVersionDetail;
}

export interface FetchAgentVersionDetailResult {
  success: boolean;
  data: AgentVersionDetail;
  message: string;
}

/**
 * Agent version list
 */
export interface AgentVersionListData {
  items: AgentVersion[];
  total: number;
}

export interface AgentVersionListResponse {
  success: boolean;
  data: AgentVersionListData;
  message: string;
}

export interface FetchAgentVersionListResult {
  success: boolean;
  data: AgentVersionListData;
  message: string;
}

/**
 * Request model for publishing a version
 */
export interface VersionPublishRequest {
  version_name?: string;
  release_note?: string;
}

/**
 * Response model for publish version
 */
export interface VersionPublishResponse {
  success: boolean;
  message: string;
  data?: AgentVersion;
}

/**
 * Request model for rollback version
 */
export interface VersionRollbackRequest {
  version_name?: string;
  release_note?: string;
}

/**
 * Response model for rollback version
 */
export interface VersionRollbackResponse {
  success: boolean;
  message: string;
  data?: AgentVersion;
}

/**
 * Request model for version comparison
 */
export interface VersionCompareRequest {
  version_no_a: number;
  version_no_b: number;
}

/**
 * Response model for version comparison
 */
export interface VersionCompareResponse {
  success: boolean;
  message: string;
  data?: {
    version_a: AgentVersionDetail;
    version_b: AgentVersionDetail;
    differences: VersionDifference[];
  };
}

/**
 * Version difference item
 */
export interface VersionDifference {
  field: string;
  label: string;
  value_a: any;
  value_b: any;
}

/**
 * Fetch agent version from backend
 * @param agentId The agent ID
 * @param versionNo The version number to fetch
 * @returns Promise containing the version response
 */
export async function fetchAgentVersion(
  agentId: number,
  versionNo: number
): Promise<FetchAgentVersionResult> {
  try {
    const response = await fetch(API_ENDPOINTS.agent.versions.version(agentId, versionNo), {
      method: "GET",
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data: AgentVersion = await response.json();
    return {
      success: true,
      data: data || {},
      message: "",
    };
  } catch (error) {
    log.error("Failed to fetch agent version:", error);
    return {
      success: false,
      data: {} as AgentVersion,
      message: "Failed to fetch agent version",
    };
  }
}

/**
 * Fetch agent version detail from backend
 * @param agentId The agent ID
 * @param versionNo The version number to fetch
 * @returns Promise containing the version detail response
 */
export async function fetchAgentVersionDetail(
  agentId: number,
  versionNo: number
): Promise<FetchAgentVersionDetailResult> {
  try {
    const response = await fetch(
      API_ENDPOINTS.agent.versions.detail(agentId, versionNo),
      {
        method: "GET",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data: AgentVersionDetail = await response.json();
    return {
      success: true,
      data: data || {},
      message: "",
    };
  } catch (error) {
    log.error("Failed to fetch agent version info:", error);
    return {
      success: false,
      data: {} as AgentVersionDetail,
      message: "Failed to fetch agent version info",
    };
  }
}

/**
 * Fetch agent version list from backend
 * @param agentId The agent ID to fetch versions for
 * @param tenantId optional tenant ID for filtering
 * @returns Promise containing the version list response
 */
export async function fetchAgentVersionList(
  agentId: number,
  tenantId?: string
): Promise<FetchAgentVersionListResult> {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.agent.versions.list(agentId)}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.agent.versions.list(agentId);
    const response = await fetch(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data: AgentVersionListData = await response.json();
    return {
      success: true,
      data: data || { items: [], total: 0 },
      message: "",
    };
  } catch (error) {
    log.error("Failed to fetch agent version list:", error);
    return {
      success: false,
      data: { items: [], total: 0 },
      message: "Failed to fetch agent version list",
    };
  }
}

/**
 * Publish a new version of an agent
 * @param agentId The agent ID to publish
 * @param request Version publish request containing version_name and release_note
 * @returns Promise containing the publish result
 */
export async function publishVersion(
  agentId: number,
  request: VersionPublishRequest
): Promise<VersionPublishResponse> {
  try {
    const response = await fetch(API_ENDPOINTS.agent.publish(agentId), {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data: AgentVersion = await response.json();
    return {
      success: true,
      message: "Version published successfully",
      data: data,
    };
  } catch (error) {
    log.error("Failed to publish agent version:", error);
    return {
      success: false,
      message: error instanceof Error ? error.message : "Failed to publish version",
    };
  }
}

/**
 * Rollback to a specific version by updating current_version_no only
 * This does NOT create a new version - the draft will point to the target version
 * Use publishVersion to create an actual new version after rollback
 * @param agentId The agent ID to rollback
 * @param sourceVersionNo The source version number to rollback to
 * @returns Promise containing the rollback result
 */
export async function rollbackVersion(
  agentId: number,
  sourceVersionNo: number
): Promise<VersionRollbackResponse> {
  try {
    const response = await fetch(
      API_ENDPOINTS.agent.versions.rollback(agentId, sourceVersionNo),
      {
        method: "POST",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data: AgentVersion = await response.json();
    return {
      success: true,
      message: "Version rolled back successfully",
      data: data,
    };
  } catch (error) {
    log.error("Failed to rollback agent version:", error);
    return {
      success: false,
      message: error instanceof Error ? error.message : "Failed to rollback version",
    };
  }
}

/**
 * Compare two versions and return their differences
 * @param agentId The agent ID
 * @param versionNoA First version number for comparison
 * @param versionNoB Second version number for comparison
 * @returns Promise containing the comparison result
 */
export async function compareVersions(
  agentId: number,
  versionNoA: number,
  versionNoB: number
): Promise<VersionCompareResponse> {
  try {
    const response = await fetch(API_ENDPOINTS.agent.versions.compare(agentId), {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        version_no_a: versionNoA,
        version_no_b: versionNoB,
      }),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    return {
      success: true,
      message: "Version comparison successful",
      data: data,
    };
  } catch (error) {
    log.error("Failed to compare agent versions:", error);
    return {
      success: false,
      message: error instanceof Error ? error.message : "Failed to compare versions",
    };
  }
}

/**
 * Delete a specific version
 * @param agentId The agent ID
 * @param versionNo The version number to delete
 * @returns Promise containing the delete result
 */
export async function deleteVersion(
  agentId: number,
  versionNo: number
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(
      API_ENDPOINTS.agent.versions.delete(agentId, versionNo),
      {
        method: "DELETE",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    return {
      success: true,
      message: "Version deleted successfully",
    };
  } catch (error) {
    log.error("Failed to delete agent version:", error);
    return {
      success: false,
      message: error instanceof Error ? error.message : "Failed to delete version",
    };
  }
}