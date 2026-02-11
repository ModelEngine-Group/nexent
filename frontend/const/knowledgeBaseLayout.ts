/**
 * Knowledge Base List Layout Constants
 *
 * Shared layout configuration for knowledge base list components.
 * Used by both KnowledgeBaseList (standalone page) and KnowledgeBaseSelectorModal (popup).
 */

// Knowledge base layout constants configuration
export const KB_LAYOUT = {
  // Row padding
  ROW_PADDING: "py-3",
  // Header padding
  HEADER_PADDING: "p-3",
  // Button area padding
  BUTTON_AREA_PADDING: "p-2",
  // Tag spacing
  TAG_SPACING: "gap-1",
  // Tag margin
  TAG_MARGIN: "mt-1.5",
  // Tag padding
  TAG_PADDING: "px-2 py-0.5",
  // Tag text style
  TAG_TEXT: "text-xs font-medium",
  // Tag rounded corners
  TAG_ROUNDED: "rounded-md",
  // Line break height
  TAG_BREAK_HEIGHT: "h-0.5",
  // Second row tag margin
  SECOND_ROW_TAG_MARGIN: "mt-1",
  // Title margin
  TITLE_MARGIN: "ml-2",
  // Empty state padding
  EMPTY_STATE_PADDING: "py-4",
  // Title text style
  TITLE_TEXT: "text-lg font-bold",
  // Knowledge base name text style
  KB_NAME_TEXT: "text-base font-medium",
  // Knowledge base name max width
  KB_NAME_MAX_WIDTH: "220px",
  // Knowledge base name overflow style
  KB_NAME_OVERFLOW: {
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    overflow: "hidden",
    display: "block",
  },
} as const;

// Tag style variants for different contexts
export const KB_TAG_VARIANTS = {
  // Default gray tag (used in modal)
  default: "bg-gray-100 text-gray-600 border border-gray-200",
  // Light gray tag (used in list)
  light: "bg-gray-200 text-gray-800 border border-gray-200",
  // Green tag for model
  model: "bg-green-50 text-green-700 border border-green-200",
  // Yellow tag for model mismatch
  warning: "bg-yellow-100 text-yellow-800 border border-yellow-200",
} as const;
