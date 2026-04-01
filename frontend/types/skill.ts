/**
 * Skill-related type definitions and constants
 */

// ========== Constants ==========

/**
 * Maximum number of recent skills to display in dropdown
 */
export const MAX_RECENT_SKILLS = 5;

/**
 * Temporary file name for skill creator drafts
 */
export const SKILL_CREATOR_TEMP_FILE = "tmp.md";

/**
 * Interactive skill creation steps (Chinese)
 */
export const THINKING_STEPS_ZH = [
  { step: 0, description: "等待大模型响应 ..." },
  { step: 1, description: "查询草稿内容 ..." },
  { step: 2, description: "生成技能 SKILL.md ..." },
  { step: 3, description: "解析并保存 ..." },
  { step: 4, description: "总结中 ..." },
];

/**
 * Interactive skill creation steps (English)
 */
export const THINKING_STEPS_EN = [
  { step: 0, description: "Waiting for model response..." },
  { step: 1, description: "Reading draft content..." },
  { step: 2, description: "Generating skill SKILL.md ..." },
  { step: 3, description: "Parsing and saving..." },
  { step: 4, description: "Summarizing..." },
];

/**
 * Content height for skill detail preview
 */
export const SKILL_DETAIL_CONTENT_HEIGHT = 300;

// ========== Interfaces ==========

/**
 * Skill form data structure
 */
export interface SkillFormData {
  name: string;
  description: string;
  source: string;
  tags: string[];
  content: string;
}

/**
 * Chat message structure for interactive skill creation
 */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

/**
 * Result of parsing a skill draft from AI response
 */
export interface CreateSimpleSkillRequest {
  user_request: string;
}

/**
 * Result of parsing a skill draft from AI response
 */
export interface SkillDraftResult {
  name: string;
  description: string;
  tags: string[];
  content: string;
}

/**
 * Skill file tree node type
 */
export interface SkillFileNode {
  name: string;
  type: "file" | "directory";
  children?: SkillFileNode[];
}

/**
 * Extended data node for Ant Design Tree
 */
export interface ExtendedSkillFileNode {
  key: React.Key;
  title: string;
  icon?: React.ReactNode;
  isLeaf?: boolean;
  children?: ExtendedSkillFileNode[];
  data?: SkillFileNode;
  fullPath?: string;
}

/**
 * Skill creation mode (create new or update existing)
 */
export type SkillCreationMode = "create" | "update";

/**
 * Skill build tab type
 */
export type SkillBuildTab = "interactive" | "upload";
