/**
 * Market types for skill marketplace
 */

export interface SkillCategory {
  id: number;
  name: string;
  display_name: string;
  display_name_zh: string;
  description: string;
  description_zh: string;
  icon: string;
  sort_order: number;
}

export interface SkillTag {
  id: number;
  name: string;
  display_name: string;
}

export interface SkillMarketItem {
  id: number;
  skill_id: string;
  name: string;
  display_name: string;
  display_name_zh: string;
  description: string;
  description_zh: string;
  author: string;
  author_url?: string;
  category: SkillCategory;
  tags: SkillTag[];
  download_count: number;
  is_featured: boolean;
  content: string;
  content_zh: string;
  source_repo: string;
  created_at: string;
  updated_at: string;
}

export interface SkillMarketDetail extends SkillMarketItem {
  usage_examples?: string;
  usage_examples_zh?: string;
  requirements?: string;
  requirements_zh?: string;
}
