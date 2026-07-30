// ========== Market Configuration Constants ==========

/**
 * Default icons for market agent categories.
 * Values are lucide-react icon names — the card component maps them to
 * actual icon components.  This keeps the config serialisable (JSON-safe)
 * while still being strongly typed.
 */
export const MARKET_CATEGORY_ICONS: Record<string, string> = {
  knowledge: "BookOpen",
  "customer-service": "Headphones",
  data: "BarChart3",
  content: "PenLine",
  research: "Search",
  finance: "TrendingUp",
  coding: "Code2",
  file: "FileText",
  email: "Mail",
  document: "FileText",
  multimodal: "Image",
  research_team: "Users",
  // legacy keys kept for backwards compatibility
  research_legacy: "Search",
  content_legacy: "PenLine",
  development: "Code2",
  business: "TrendingUp",
  automation: "Settings",
  education: "GraduationCap",
  communication: "MessageSquare",
  creative: "Palette",
  other: "Package",
} as const;

/**
 * Get lucide icon name for a category by name field.
 * @param categoryName - Category name field (e.g., "knowledge", "data")
 * @param fallbackIcon - Fallback icon name if category not found
 * @returns lucide-react icon name string
 */
export function getCategoryIcon(
  categoryName: string | null | undefined,
  fallbackIcon: string = "Package"
): string {
  if (!categoryName) {
    return fallbackIcon;
  }

  return MARKET_CATEGORY_ICONS[categoryName] || fallbackIcon;
}
