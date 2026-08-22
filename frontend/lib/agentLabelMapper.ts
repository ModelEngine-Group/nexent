/**
 * Agent Label Mapper Utility
 * Provides unified label mapping for tool sources, agent types, and other labels
 * across the application with i18n support
 */

import { TFunction } from "i18next";

/**
 * Mapping of unavailable reason keys to i18n translation keys
 */
export const UNAVAILABLE_REASON_I18N_MAP: Record<string, string> = {
  duplicate_name: "agent.unavailableReasons.duplicate_name",
  duplicate_display_name: "agent.unavailableReasons.duplicate_display_name",
  tool_unavailable: "agent.unavailableReasons.tool_unavailable",
  model_unavailable: "agent.unavailableReasons.model_unavailable",
  all_tools_disabled: "agent.unavailableReasons.all_tools_disabled",
  model_not_configured: "agent.unavailableReasons.model_not_configured",
  agent_not_found: "agent.unavailableReasons.agent_not_found",
};

/**
 * Get localized label for an unavailable reason
 * @param reason - The unavailable reason key from backend
 * @param t - Translation function from i18next
 * @returns Localized reason label
 */
export function getUnavailableReasonLabel(reason: string, t: TFunction): string {
  const i18nKey = UNAVAILABLE_REASON_I18N_MAP[reason];
  if (i18nKey) {
    return t(i18nKey);
  }
  return reason;
}

/**
 * Get localized labels for multiple unavailable reasons
 * @param reasons - Array of unavailable reason keys
 * @param t - Translation function from i18next
 * @returns Array of localized reason labels
 */
export function getUnavailableReasonLabels(
  reasons: string[],
  t: TFunction
): string[] {
  return (reasons || []).map((r) => getUnavailableReasonLabel(r, t));
}

/**
 * Map tool source to localized label
 * @param source - Tool source (local, mcp, langchain, etc.)
 * @param t - Translation function from i18next
 * @returns Localized tool source label
 */
export function getToolSourceLabel(source: string, t: TFunction): string {
  const sourceLower = source?.toLowerCase() || "";
  
  switch (sourceLower) {
    case "local":
      return t("common.toolSource.local", "Local Tool");
    case "mcp":
      return t("common.toolSource.mcp", "MCP Tool");
    case "langchain":
      return t("common.toolSource.langchain", "LangChain Tool");
    default:
      return source;
  }
}

/**
 * Map agent type to localized label
 * @param type - Agent type (single agent, multi agent, etc.)
 * @param t - Translation function from i18next
 * @returns Localized agent type label
 */
export function getAgentTypeLabel(type: string, t: TFunction): string {
  const typeLower = type?.toLowerCase() || "";
  
  switch (typeLower) {
    case "single agent":
      return t("common.agentType.single", "Single Agent");
    case "multi agent":
      return t("common.agentType.multi", "Multi Agent");
    default:
      return type;
  }
}

/**
 * Map generic tag/label to localized label
 * Handles both tool sources and agent types
 * @param label - Tag or label name
 * @param t - Translation function from i18next
 * @returns Localized label
 */
export function getGenericLabel(label: string, t: TFunction): string {
  const labelLower = label?.toLowerCase() || "";
  
  // Check tool sources first
  if (["local", "mcp", "langchain"].includes(labelLower)) {
    return getToolSourceLabel(label, t);
  }
  
  // Check agent types
  if (["single agent", "multi agent"].includes(labelLower)) {
    return getAgentTypeLabel(label, t);
  }
  
  // Return original if no mapping found
  return label;
}

/**
 * Map category to localized label (for tool categories)
 * @param category - Category name
 * @param t - Translation function from i18next
 * @returns Localized category label
 */
export function getCategoryLabel(category: string, t: TFunction): string {
  // For now, category mapping is the same as agent type mapping
  // Can be extended if different mappings are needed
  return getAgentTypeLabel(category, t);
}

