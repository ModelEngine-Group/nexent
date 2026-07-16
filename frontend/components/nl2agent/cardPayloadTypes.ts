import type { components as Nl2AgentApiComponents } from "@/contracts/generated/nl2agent-api";

import type { WebMcpCardItem } from "./webMcpTypes";

type Nl2AgentApiSchemas = Nl2AgentApiComponents["schemas"];
type WithOptionalAgentId = { agent_id?: number };

export type RequirementsSummaryCardPayload =
  Nl2AgentApiSchemas["Nl2AgentRequirementsSummaryRequest"] &
    WithOptionalAgentId;

export type ModelSelectionCardPayload = WithOptionalAgentId;

export interface LocalToolCardItem {
  tool_id: number;
  name: string;
  description?: string;
  labels?: string[];
  source?: string;
  category?: string;
  usage?: string;
  score?: number;
  reason?: string;
}

export interface LocalSkillCardItem {
  skill_id: number;
  name: string;
  description?: string;
  tags?: string[];
  score?: number;
  reason?: string;
}

export interface LocalResourcesCardPayload extends WithOptionalAgentId {
  recommendation_batch_id: string;
  tools: LocalToolCardItem[];
  skills: LocalSkillCardItem[];
}

export type WebMcpCardPayload = WebMcpCardItem &
  Required<Pick<WebMcpCardItem, "recommendation_id" | "install_options">> & {
    agent_id?: number;
    recommendation_batch_id: string;
  };

export interface WebMcpListCardPayload extends WithOptionalAgentId {
  recommendation_batch_id: string;
  items: Array<
    WebMcpCardItem &
      Required<Pick<WebMcpCardItem, "recommendation_id" | "install_options">> &
      WithOptionalAgentId
  >;
}

interface WebSkillCardItemFields extends WithOptionalAgentId {
  recommendation_batch_id?: string;
  skill_id?: number;
  description?: string;
  tags?: string[];
  source?: string;
  status?: string;
  score?: number;
  reason?: string;
}

export type WebSkillCardPayloadItem = WebSkillCardItemFields &
  (
    | { name: string; skill_name?: string }
    | { name?: string; skill_name: string }
  ) &
  ({ skill_id: number } | { skill_name: string });

export type WebSkillCardPayload = WebSkillCardPayloadItem & {
  recommendation_batch_id: string;
};

export interface WebSkillListCardPayload extends WithOptionalAgentId {
  recommendation_batch_id: string;
  items: WebSkillCardPayloadItem[];
}

export interface AgentIdentityCardPayload extends WithOptionalAgentId {
  display_name: string;
}

export type FinalizeVerificationConfig = NonNullable<
  Nl2AgentApiSchemas["Nl2AgentFinalizeRequest"]["verification_config"]
> & { enabled: boolean };

export interface FinalReviewCardPayload extends WithOptionalAgentId {
  description?: string;
  business_description: string;
  duty_prompt: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;
  greeting_message: string;
  example_questions?: string[];
  max_steps?: number;
  requested_output_tokens?: number;
  provide_run_summary?: boolean;
  verification_config?: FinalizeVerificationConfig;
  enable_context_manager?: boolean;
}

export type FinalizeCardData = FinalReviewCardPayload & { agent_id: number };

export type WebSkillCardItem = WebSkillCardPayloadItem & { name: string };

export const toWebSkillCardItem = (
  item: WebSkillCardPayloadItem
): WebSkillCardItem => {
  if (typeof item.name === "string") return { ...item, name: item.name };
  if (typeof item.skill_name === "string") {
    return { ...item, name: item.skill_name };
  }
  throw new Error("Validated web skill card is missing its display name");
};

export const webSkillRecommendationKey = (item: WebSkillCardItem): string => {
  if (typeof item.skill_id === "number") return `skill:${item.skill_id}`;
  if (typeof item.skill_name === "string") {
    return `skill-name:${item.skill_name.trim().toLowerCase()}`;
  }
  throw new Error("Validated web skill card is missing its stable key");
};
