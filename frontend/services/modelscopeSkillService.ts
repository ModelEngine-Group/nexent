import { getAuthHeaders } from "@/lib/auth";
import type {
  ModelScopeMarketListResponse,
  ModelScopeMarketSkill,
  ModelScopeSkillInstallPayload,
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
  skillId: string
): Promise<ModelScopeMarketSkill> {
  const query = new URLSearchParams({ skill_id: skillId });
  const response = await fetchWithErrorHandling(
    `${API_ENDPOINTS.skills.marketDetail}?${query.toString()}`,
    { headers: getAuthHeaders() }
  );
  return response.json();
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
