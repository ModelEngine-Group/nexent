import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";

export type Nl2AgentSkillCreationEvent =
  | "exposure"
  | "create_click"
  | "create_cancel"
  | "create_success"
  | "verification_success"
  | "verification_failed"
  | "weak_match_accepted"
  | "non_skill_resource_selected"
  | "requirement_abandoned";

export interface Nl2AgentSkillCreationEventPayload {
  event: Nl2AgentSkillCreationEvent;
  non_skill_coverage?: "installed" | "installable" | "none";
  created_skill_status?: "unverified" | "weak_match" | "none";
  has_weak_matches?: boolean;
}

export const recordNl2AgentSkillCreationEvent = async (
  payload: Nl2AgentSkillCreationEventPayload
): Promise<void> => {
  await fetchWithAuth(API_ENDPOINTS.agent.nl2agentSkillCreationEvents, {
    method: "POST",
    body: JSON.stringify(payload),
  });
};
