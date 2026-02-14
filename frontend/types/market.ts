/**
 * Market types for agent marketplace
 */

export interface MarketCategory {
  id: number;
  name: string;
  display_name: string;
  display_name_zh: string;
  description: string;
  description_zh: string;
  icon: string;
  sort_order: number;
  created_at: string;
}

export interface MarketTag {
  id: number;
  name: string;
  display_name: string;
  description: string;
  created_at: string;
}

export interface MarketAgentListItem {
  id: number;
  agent_id: number;
  name: string;
  display_name: string;
  description: string;
  author?: string;
  category?: MarketCategory;
  tags: MarketTag[];
  download_count: number;
  created_at: string;
  tool_count?: number;
  is_featured: boolean;
}

export interface MarketAgentTool {
  id: number;
  class_name: string;
  name: string;
  description: string;
  description_zh?: string;
  output_type: string;
  params: Record<string, any>;
  source: string;
  usage: string | null;
  tool_metadata: Record<string, any> | null;
  inputs?: Record<string, any>;
}

export interface MarketMcpServer {
  id: number;
  mcp_server_name: string;
  mcp_url: string;
}

export interface MarketAgentDetail extends MarketAgentListItem {
  business_description: string;
  max_steps: number;
  provide_run_summary: boolean;
  duty_prompt: string;
  constraint_prompt: string;
  few_shots_prompt: string;
  enabled: boolean;
  model_id: number;
  model_name: string;
  business_logic_model_id: number;
  business_logic_model_name: string;
  tools: MarketAgentTool[];
  mcp_servers: MarketMcpServer[];
  updated_at: string;
  agent_json: {
    agent_id: number;
    mcp_info: Array<{
      mcp_server_name: string;
      mcp_url: string;
    }>;
    agent_info: Record<string, any>;
  };
}

export interface MarketPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface MarketAgentListResponse {
  items: MarketAgentListItem[];
  pagination: MarketPagination;
  // Optional featured items returned by the API when requested
  featured_items?: MarketAgentListItem[];
}

export interface MarketAgentListParams {
  page?: number;
  page_size?: number;
  category?: string;
  tag?: string;
  search?: string;
  lang?: string;
}

