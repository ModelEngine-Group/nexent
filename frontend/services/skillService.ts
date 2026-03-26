import { API_ENDPOINTS } from "./api";
import { fetchWithAuth } from "@/lib/auth";
import log from "@/lib/logger";

export interface SkillListItem {
  skill_id: number;
  name: string;
  description: string | null;
  tags: string[];
  content: string;
  params: Record<string, unknown> | null;
  source: string;
  tool_ids: number[];
  created_by?: string | null;
  create_time?: string | null;
  updated_by?: string | null;
  update_time?: string | null;
}

/**
 * Fetches all skills from the config service (GET /api/skills).
 */
export async function fetchSkillsList(): Promise<SkillListItem[]> {
  const response = await fetchWithAuth(API_ENDPOINTS.skills.list, {
    method: "GET",
  });
  const data = await response.json();
  const skills = data?.skills;
  if (!Array.isArray(skills)) {
    log.warn("skills list response missing skills array", data);
    return [];
  }
  return skills as SkillListItem[];
}

/**
 * Request body for PUT /api/skills/{skill_name} (matches backend SkillUpdateRequest).
 * Omit fields that should stay unchanged.
 */
export interface SkillUpdateBody {
  description?: string;
  content?: string;
  tool_ids?: number[];
  tool_names?: string[];
  tags?: string[];
  source?: string;
  params?: Record<string, unknown> | null;
}

/**
 * Updates a skill via PUT /api/skills/{skill_name} (proxied to config service, e.g. port 5010).
 * Example: updateSkill("my_skill", { params: { key: "value" } }) — same as curl with JSON body.
 */
export async function updateSkill(
  skillName: string,
  body: SkillUpdateBody
): Promise<SkillListItem> {
  const response = await fetchWithAuth(API_ENDPOINTS.skills.update(skillName), {
    method: "PUT",
    body: JSON.stringify(body),
  });
  return response.json() as Promise<SkillListItem>;
}
