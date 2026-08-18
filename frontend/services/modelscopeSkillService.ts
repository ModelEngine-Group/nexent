import { getAuthHeaders } from "@/lib/auth";
import type {
  InstalledMarketSkill,
  ModelScopeMarketListResponse,
  ModelScopeSkillInstallPayload,
  ModelScopeSkillUpdatePayload,
} from "@/types/skill";
import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";

export async function fetchModelScopeSkills(params: {
  search?: string;
  pageNumber: number;
  pageSize: number;
}): Promise<ModelScopeMarketListResponse> {
  const query = new URLSearchParams({
    page_number: String(params.pageNumber),
    page_size: String(params.pageSize),
  });
  if (params.search?.trim()) query.set("search", params.search.trim());
  const response = await fetchWithErrorHandling(
    `${API_ENDPOINTS.skills.marketList}?${query.toString()}`,
    { headers: getAuthHeaders() }
  );
  return response.json();
}

export async function fetchModelScopeSkillDetail(
  skillId: string,
  source = "modelscope"
): Promise<InstalledMarketSkill | Record<string, never>> {
  const query = new URLSearchParams({ skill_id: skillId, source });
  const response = await fetchWithErrorHandling(
    `${API_ENDPOINTS.skills.marketDetail}?${query.toString()}`,
    { headers: getAuthHeaders() }
  );
  return response.json();
}

export function parseInstalledMarketSkill(
  result: InstalledMarketSkill | Record<string, never>
): InstalledMarketSkill | null {
  const skillId = Number(
    (result as { skill_id?: unknown }).skill_id
  );
  if (!Number.isInteger(skillId) || skillId <= 0) {
    return null;
  }
  const record = result as InstalledMarketSkill;
  return {
    skill_id: skillId,
    name: typeof record.name === "string" ? record.name : null,
    description:
      typeof record.description === "string" ? record.description : null,
    source: typeof record.source === "string" ? record.source : null,
    tags: Array.isArray(record.tags)
      ? record.tags.filter((tag): tag is string => typeof tag === "string")
      : [],
    group_ids: Array.isArray(record.group_ids)
      ? record.group_ids.filter((id): id is number => typeof id === "number")
      : [],
    ingroup_permission: record.ingroup_permission ?? null,
    created_by:
      typeof record.created_by === "string" ? record.created_by : null,
    version_update_time:
      typeof record.version_update_time === "string"
        ? record.version_update_time
        : null,
  };
}

export async function installModelScopeSkill(
  payload: ModelScopeSkillInstallPayload
): Promise<{ skill_id: number; name: string }> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.skills.marketInstall,
    {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return response.json();
}

export async function updateModelScopeSkill(
  payload: ModelScopeSkillUpdatePayload
): Promise<{ skill_id: number; name?: string }> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.skills.marketUpdate,
    {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return response.json();
}
