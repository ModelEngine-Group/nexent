/**
 * Label resolvers for agent repository preset tags.
 * Presets live in const/agentRepository.ts; localized labels come from i18n.
 */

import type { TFunction } from "i18next";
import { AGENT_REPOSITORY_PRESET_TAGS } from "@/const/agentRepository";

/** Map preset tag key to i18n key suffix under agentRepository.tag.* */
const TAG_KEY_TO_I18N: Record<string, string> = Object.fromEntries(
  AGENT_REPOSITORY_PRESET_TAGS.map((tag) => [
    tag,
    tag
      .split("_")
      .map((part, index) =>
        index === 0 ? part : part.charAt(0).toUpperCase() + part.slice(1)
      )
      .join(""),
  ])
);

/** Legacy Chinese preset tag values stored before stable keys were introduced. */
const LEGACY_TAG_VALUE_TO_KEY: Record<string, string> = {
  营销: "marketing",
  文案: "copywriting",
  内容创作: "content_creation",
  代码审查: "code_review",
  质量: "quality",
  DevOps: "devops",
  数据: "data",
  可视化: "visualization",
  BI: "bi",
  客服: "customer_service",
  工单: "ticket",
  自动化: "automation",
  会议: "meeting",
  纪要: "minutes",
  效率: "productivity",
  设计: "design",
  配色: "color_scheme",
  灵感: "inspiration",
  表格: "spreadsheet",
  办公: "office",
};

function resolveTagKey(tag: string): string | null {
  const trimmed = tag.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed in TAG_KEY_TO_I18N) {
    return trimmed;
  }
  return LEGACY_TAG_VALUE_TO_KEY[trimmed] ?? null;
}

/**
 * Get localized label for a repository tag (preset key or legacy Chinese value).
 * Custom tags are returned unchanged.
 */
export function getAgentRepositoryTagLabel(tag: string, t: TFunction): string {
  const stableKey = resolveTagKey(tag);
  if (stableKey) {
    const i18nSuffix = TAG_KEY_TO_I18N[stableKey];
    if (i18nSuffix) {
      const i18nKey = `agentRepository.tag.${i18nSuffix}`;
      const translated = t(i18nKey);
      if (translated !== i18nKey) {
        return translated;
      }
    }
  }
  return tag.trim();
}

/**
 * Resolve a tag for API submission: preset tags become the localized i18n value
 * for the current locale; custom tags are trimmed as-is.
 */
export function resolveAgentRepositoryTagForSubmit(
  tag: string,
  t: TFunction
): string {
  const trimmed = tag.trim();
  if (!trimmed) {
    return trimmed;
  }
  if (resolveTagKey(trimmed)) {
    return getAgentRepositoryTagLabel(trimmed, t);
  }
  return trimmed;
}

/**
 * Build searchable text for a tag (raw value + localized label).
 */
export function getAgentRepositoryTagSearchText(tag: string, t: TFunction): string {
  const label = getAgentRepositoryTagLabel(tag, t);
  return `${tag} ${label}`.toLowerCase();
}

const REQUIREMENT_TYPE_I18N: Record<string, string> = {
  model: "agentRepository.copy.type.model",
  knowledge_base: "agentRepository.copy.type.knowledgeBase",
  mcp: "agentRepository.copy.type.mcp",
  skill: "agentRepository.copy.type.skill",
  tool: "agentRepository.copy.type.tool",
};

const REQUIREMENT_ACTIVATE_PATH: Record<string, string> = {
  model: "/models",
  knowledge_base: "/knowledges",
  mcp: "/mcp-space",
  skill: "/skill-space",
};

const REQUIREMENT_TYPE_ORDER = [
  "model",
  "knowledge_base",
  "mcp",
  "skill",
  "tool",
] as const;

export function getRepositoryRequirementTypeLabel(
  type: string,
  t: TFunction
): string {
  const key = REQUIREMENT_TYPE_I18N[type];
  return key ? t(key) : type;
}

export function getRepositoryRequirementActivatePath(type: string): string | null {
  return REQUIREMENT_ACTIVATE_PATH[type] ?? null;
}

export function getRepositoryRequirementTypeOrder(): readonly string[] {
  return REQUIREMENT_TYPE_ORDER;
}

export function getRepositoryRequirementReasonLabel(
  reasonCode: string | null | undefined,
  t: TFunction
): string {
  if (!reasonCode) {
    return "";
  }
  const key = `agentRepository.copy.reason.${reasonCode}`;
  const translated = t(key);
  return translated === key ? reasonCode : translated;
}
