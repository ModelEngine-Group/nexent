import i18next from 'i18next';

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { fetchAllAgents } from "./agentConfigService";

import { MemoryItem, MemoryGroup } from "@/types/memory";
import { getAuthHeaders } from '@/lib/auth';
import log from "@/lib/logger";

// ---------------------------------------------------------------------------
// Error message translation helper
// ---------------------------------------------------------------------------
function getFriendlyErrorMessage(raw: string): string {
  let msg = raw;
  try {
    const obj = JSON.parse(raw);
    // Backend now raises HTTPException with { detail }
    if (obj && typeof obj.detail === "string") {
      msg = obj.detail;
    } else if (obj && typeof obj.message === "string") {
      msg = obj.message;
    }
  } catch (_) {
    // ignore JSON parse errors
  }

  // Keyword mapping to user-friendly Chinese prompts
  if (/AuthenticationException/i.test(msg)) {
    return "Elasticsearch authentication failed";
  } else if (/ConnectionTimeout/i.test(msg)) {
    return "Connection to language model timed out";
  } else if (/unhashable type: 'slice'/i.test(msg)) {
    return "Backend data slicing error. Please contact administrator";
  }

  return msg;
}

/**
 * NOTE: The first half of this file still contains mock helpers which are useful
 * for Storybook/isolated UI tests.  The bottom section implements real API
 * integrations that will be used at runtime.
 * ---------------------------------------------------------------------------
 */

// ---------------------------------------------------------------------------
// Helper for unified JSON request/response handling
// ---------------------------------------------------------------------------
async function requestJson(
  url: string,
  options: RequestInit = {}
): Promise<any> {
  const resp = await fetchWithErrorHandling(url, options);
  return resp.json();
}

// ---------------------------------------------------------------------------
// Configuration helpers
// ---------------------------------------------------------------------------
export interface MemoryConfig {
  memoryEnabled: boolean;
  shareOption: "always" | "ask" | "never";
  disableAgentIds: string[];
  disableUserAgentIds: string[];
}

export async function loadMemoryConfig(): Promise<MemoryConfig> {
  try {
    const res = await requestJson(API_ENDPOINTS.memory.config.load, {
      method: "GET",
      headers: getAuthHeaders(),
    });

    // Backend returns plain config object directly
    const cfg = res || {};

    const memorySwitchVal: string =
      cfg.MEMORY_SWITCH ?? cfg.memory_switch ?? "Y";
    const shareVal: string =
      cfg.MEMORY_AGENT_SHARE ?? cfg.memory_agent_share ?? "always";
    const disableAgentIds: string[] =
      cfg.DISABLE_AGENT_ID ?? cfg.disable_agent_id ?? [];
    const disableUserAgentIds: string[] =
      cfg.DISABLE_USERAGENT_ID ?? cfg.disable_useragent_id ?? [];

    return {
      memoryEnabled: memorySwitchVal === "Y",
      shareOption: (shareVal || "always") as "always" | "ask" | "never",
      disableAgentIds,
      disableUserAgentIds,
    };
  } catch (e) {
    log.error("loadMemoryConfig error", e);
    // fall back to defaults
    return {
      memoryEnabled: true,
      shareOption: "always",
      disableAgentIds: [],
      disableUserAgentIds: [],
    };
  }
}

export async function setMemorySwitch(enabled: boolean): Promise<boolean> {
  try {
    const body = { key: "MEMORY_SWITCH", value: enabled };
    const res = await requestJson(API_ENDPOINTS.memory.config.set, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(body),
    });
    // Backend returns { success: true } on OK
    return !!res?.success;
  } catch (e) {
    log.error("setMemorySwitch error", e);
    return false;
  }
}

export async function setMemoryAgentShare(
  option: "always" | "ask" | "never"
): Promise<boolean> {
  try {
    const body = { key: "MEMORY_AGENT_SHARE", value: option };
    const res = await requestJson(API_ENDPOINTS.memory.config.set, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(body),
    });
    return !!res?.success;
  } catch (e) {
    log.error("setMemoryAgentShare error", e);
    return false;
  }
}

// ---------------- Disable list helpers ----------------
export async function addDisabledAgentId(agentId: string): Promise<boolean> {
  try {
    const res = await requestJson(API_ENDPOINTS.memory.config.disableAgentAdd, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ agent_id: agentId }),
    });
    return !!res?.success;
  } catch (e) {
    log.error("addDisabledAgentId error", e);
    return false;
  }
}

export async function removeDisabledAgentId(agentId: string): Promise<boolean> {
  try {
    const res = await requestJson(
      API_ENDPOINTS.memory.config.disableAgentRemove(agentId),
      {
        method: "DELETE",
        headers: getAuthHeaders(),
      }
    );
    return !!res?.success;
  } catch (e) {
    log.error("removeDisabledAgentId error", e);
    return false;
  }
}

export async function addDisabledUserAgentId(
  agentId: string
): Promise<boolean> {
  try {
    const res = await requestJson(
      API_ENDPOINTS.memory.config.disableUserAgentAdd,
      {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ agent_id: agentId }),
      }
    );
    return !!res?.success;
  } catch (e) {
    log.error("addDisabledUserAgentId error", e);
    return false;
  }
}

export async function removeDisabledUserAgentId(
  agentId: string
): Promise<boolean> {
  try {
    const res = await requestJson(
      API_ENDPOINTS.memory.config.disableUserAgentRemove(agentId),
      {
        method: "DELETE",
        headers: getAuthHeaders(),
      }
    );
    return !!res?.success;
  } catch (e) {
    log.error("removeDisabledUserAgentId error", e);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Memory list helpers
// ---------------------------------------------------------------------------
async function listMemories(
  memoryLevel: string,
  agentId?: string
): Promise<{ items: MemoryItem[]; total: number }> {
  const params = new URLSearchParams({ memory_level: memoryLevel });
  if (agentId) params.append("agent_id", agentId);

  const url = `${API_ENDPOINTS.memory.entry.list}?${params.toString()}`;
  try {
    const res = await requestJson(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    // Backend returns payload directly (list or object with items/total)
    const content = res ?? {};
    const items: MemoryItem[] = content.items ?? res ?? [];
    const total: number = content.total ?? items.length;
    return { items, total };
  } catch (e) {
    log.error("listMemories error", e);
    if (e instanceof Error) {
      throw new Error(getFriendlyErrorMessage(e.message || ""));
    }
    throw new Error(i18next.t("memoryService.loadMemoryError"));
  }
}

export async function fetchTenantSharedGroup(): Promise<MemoryGroup> {
  const { items } = await listMemories("tenant");
  return {
    title: i18next.t("memoryService.tenantSharedGroupTitle"),
    key: "tenant",
    items,
  };
}

export async function fetchAgentSharedGroups(): Promise<MemoryGroup[]> {
  // Parallel requests: memory list + full Agent list
  const [{ items }, agentsRes] = await Promise.all([
    listMemories("agent"),
    fetchAllAgents(),
  ]);

  // First group results with memories by agent_id
  const groupMap: Record<string, MemoryItem[]> = {};
  items.forEach((item) => {
    if (!item.agent_id) return;
    if (!groupMap[item.agent_id]) groupMap[item.agent_id] = [];
    groupMap[item.agent_id].push(item);
  });

  // Complete groups with agents that have no memories
  const agentList: Array<{
    agent_id: string;
    name?: string;
    display_name?: string;
  }> = (agentsRes as any)?.success ? (agentsRes as any).data : [];

  const groups: MemoryGroup[] = [];

  // Build groups in Agent list order to ensure completeness
  agentList.forEach((agent) => {
    const agentId = agent.agent_id;
    const list = groupMap[agentId] || [];
    groups.push({
      title: i18next.t("memoryService.agentSharedGroupTitle", {
        agentName: agent.display_name || agent.name || agentId,
      }),
      key: `agent-${agentId}`,
      items: list,
    });
  });

  // If still no agent info, return placeholder group
  if (groups.length === 0) {
    return [
      {
        title: i18next.t("memoryService.agentSharedPlaceholder"),
        key: "agent-placeholder",
        items: [],
      },
    ];
  }

  return groups;
}

export async function fetchUserPersonalGroup(): Promise<MemoryGroup> {
  const { items } = await listMemories("user");
  return {
    title: i18next.t("memoryService.userPersonalGroupTitle"),
    key: "user-personal",
    items,
  };
}

export async function fetchUserAgentGroups(): Promise<MemoryGroup[]> {
  // Parallel requests: user memory + full Agent list
  const [{ items }, agentsRes] = await Promise.all([
    listMemories("user_agent"),
    fetchAllAgents(),
  ]);

  const groupMap: Record<string, MemoryItem[]> = {};
  items.forEach((item) => {
    if (!item.agent_id) return;
    if (!groupMap[item.agent_id]) groupMap[item.agent_id] = [];
    groupMap[item.agent_id].push(item);
  });

  const agentList: Array<{
    agent_id: string | number;
    name?: string;
    display_name?: string;
  }> = (agentsRes as any)?.success ? (agentsRes as any).data : [];

  const groups: MemoryGroup[] = [];

  agentList.forEach((agent) => {
    const agentId = String(agent.agent_id);
    const list = groupMap[agentId] || [];
    groups.push({
      title: i18next.t("memoryService.userAgentGroupTitle", {
        agentName: agent.display_name || agent.name || agentId,
      }),
      key: `user-agent-${agentId}`,
      items: list,
    });
  });

  Object.entries(groupMap).forEach(([agentId, list]) => {
    if (!agentList.some((a) => String(a.agent_id) === agentId)) {
      groups.push({
        title: i18next.t("memoryService.userAgentGroupTitle", {
          agentName: list[0]?.agent_name || agentId,
        }),
        key: `user-agent-${agentId}`,
        items: list,
      });
    }
  });

  if (groups.length === 0) {
    return [
      {
        title: i18next.t("memoryService.userAgentPlaceholder"),
        key: "user-agent-placeholder",
        items: [],
      },
    ];
  }
  return groups;
}

// ---------------------------------------------------------------------------
// Memory CRUD operations
// ---------------------------------------------------------------------------

export async function addMemory(
  messages: Array<{ role: string; content: string }>,
  memoryLevel: string,
  agentId?: string,
  infer: boolean = true
): Promise<boolean> {
  try {
    const body = {
      messages,
      memory_level: memoryLevel,
      infer,
      ...(agentId && { agent_id: agentId }),
    };
    const res = await requestJson(API_ENDPOINTS.memory.entry.add, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(body),
    });
    // Backend returns inserted info or payload directly on success
    return !!res;
  } catch (e) {
    log.error("addMemory error", e);
    throw e;
  }
}

export async function clearMemory(
  memoryLevel: string,
  agentId?: string
): Promise<{ deleted_count: number; total_count: number }> {
  try {
    const params = new URLSearchParams({ memory_level: memoryLevel });
    if (agentId) params.append("agent_id", agentId);
    const url = `${API_ENDPOINTS.memory.entry.clear}?${params.toString()}`;

    const res = await requestJson(url, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    const result = res || { deleted_count: 0, total_count: 0 };
    return result;
  } catch (e) {
    log.error("clearMemory error", e);
    throw e;
  }
}

export async function deleteMemory(
  memoryId: string,
  memoryLevel: string,
  agentId?: string
): Promise<boolean> {
  try {
    const params = new URLSearchParams({ memory_level: memoryLevel });
    if (agentId) params.append("agent_id", agentId);
    const url = `${API_ENDPOINTS.memory.entry.delete(
      memoryId
    )}?${params.toString()}`;

    const res = await requestJson(url, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    return !!res;
  } catch (e) {
    log.error("deleteMemory error", e);
    throw e;
  }
}
