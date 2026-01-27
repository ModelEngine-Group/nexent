/**
 * Agent Label Mapper Utility
 * Provides unified label mapping for tool sources, agent types, and other labels
 * across the application with i18n support
 */

import { TFunction } from "i18next";

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

/**
 * Get localized tool description by tool name
 * Falls back to original description if no translation key exists
 * @param toolName - Tool name (e.g., "get_email", "send_email", "datamate_search")
 * @param originalDescription - Original description from backend (fallback)
 * @param t - Translation function from i18next
 * @returns Localized tool description
 */
export function getToolDescription(
  toolName: string,
  originalDescription: string,
  t: TFunction
): string {
  if (!toolName) {
    return originalDescription || "";
  }
  
  const translationKey = `tool.description.${toolName}`;
  const translated = t(translationKey, originalDescription);
  
  // If translation key doesn't exist, i18next returns the key itself
  // In that case, return the original description
  if (translated === translationKey) {
    return originalDescription;
  }
  
  // Return the translated value (which should be localized based on current language)
  return translated;
}

