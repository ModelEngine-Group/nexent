// ========== Market Configuration Constants ==========

/**
 * Default icons for market agent categories
 * Maps category name field to their corresponding icons
 */
export const MARKET_CATEGORY_ICONS: Record<string, string> = {
  research: "🔬",
  content: "✍️",
  development: "💻",
  business: "📈",
  automation: "⚙️",
  education: "📚",
  communication: "💬",
  data: "📊",
  creative: "🎨",
  other: "📦",
} as const;

/**
 * Get icon for a category by name field
 * @param categoryName - Category name field (e.g., "research", "content")
 * @param fallbackIcon - Fallback icon if category not found (default: 📦)
 * @returns Icon emoji string
 */
export function getCategoryIcon(
  categoryName: string | null | undefined,
  fallbackIcon: string = "📦"
): string {
  if (!categoryName) {
    return fallbackIcon;
  }
  
  return MARKET_CATEGORY_ICONS[categoryName] || fallbackIcon;
}

