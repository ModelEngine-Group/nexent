/**
 * Agent repository listing presets (categories, icons, preset tags).
 * Display labels are resolved via i18n in agentRepositoryLabels.ts.
 */

export interface AgentRepositoryCategoryPreset {
  id: number;
  key: string;
}

export const AGENT_REPOSITORY_CATEGORIES: AgentRepositoryCategoryPreset[] = [
  { id: 1, key: "writing_assistant" },
  { id: 2, key: "programming" },
  { id: 3, key: "data_analysis" },
  { id: 4, key: "customer_service" },
  { id: 5, key: "productivity" },
  { id: 6, key: "creative_design" },
  { id: 0, key: "other" },
];

export const AGENT_REPOSITORY_ICONS = [
  "🤖",
  "✍️",
  "🔍",
  "📊",
  "💬",
  "📝",
  "🎨",
  "⚡",
  "🔧",
  "📚",
] as const;

export const AGENT_REPOSITORY_PRESET_TAGS = [
  "marketing",
  "copywriting",
  "content_creation",
  "code_review",
  "quality",
  "devops",
  "data",
  "visualization",
  "bi",
  "customer_service",
  "ticket",
  "automation",
  "meeting",
  "minutes",
  "productivity",
  "design",
  "color_scheme",
  "inspiration",
  "spreadsheet",
  "office",
] as const;

/** Map category id to stable key for label resolution. */
export const AGENT_REPOSITORY_CATEGORY_ID_TO_KEY: Record<number, string> =
  Object.fromEntries(
    AGENT_REPOSITORY_CATEGORIES.map((category) => [category.id, category.key])
  );
