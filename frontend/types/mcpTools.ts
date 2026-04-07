/**
 * Types for MCP Tools marketplace
 */

export interface McpToolsCategory {
  id: number;
  name: string;
  display_name: string;
  display_name_zh: string;
  description: string;
  description_zh: string;
  icon: string;
  sort_order: number;
}

export interface McpToolsTag {
  id: number;
  name: string;
  display_name: string;
}

export interface McpToolsItem {
  id: number;
  mcp_id: string;
  name: string;
  display_name: string;
  display_name_zh: string;
  description: string;
  description_zh: string;
  author: string;
  author_url?: string;
  category: McpToolsCategory;
  tags: McpToolsTag[];
  github_stars: number;
  is_featured: boolean;
  content: string;
  content_zh: string;
  source_repo: string;
  official_url?: string;
  created_at: string;
  updated_at: string;
}

export interface McpToolsDetail extends McpToolsItem {
  usage_examples?: string;
  usage_examples_zh?: string;
  requirements?: string;
  requirements_zh?: string;
}
