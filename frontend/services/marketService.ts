/**
 * Market service for agent marketplace API calls
 */

import { API_ENDPOINTS } from './api';
import log from '@/lib/logger';
import {
  MarketAgentListResponse,
  MarketAgentDetail,
  MarketCategory,
  MarketTag,
  MarketMcpServer,
  MarketAgentListParams,
} from '@/types/market';

// Market API timeout in milliseconds (5 seconds)
const MARKET_API_TIMEOUT = 5000;

/**
 * Custom error class for market API errors
 */
export class MarketApiError extends Error {
  constructor(
    message: string,
    public type: 'timeout' | 'network' | 'server' | 'unknown' = 'unknown',
    public statusCode?: number
  ) {
    super(message);
    this.name = 'MarketApiError';
  }
}

/**
 * Fetch with timeout support
 * @param url - Request URL
 * @param options - Fetch options
 * @param timeout - Timeout in milliseconds
 * @returns Promise<Response>
 * @throws MarketApiError on timeout or network error
 */
async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeout: number = MARKET_API_TIMEOUT
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error: any) {
    clearTimeout(timeoutId);
    
    if (error.name === 'AbortError') {
      throw new MarketApiError(
        'Request timeout - market server is not responding',
        'timeout'
      );
    }
    
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
      throw new MarketApiError(
        'Network error - unable to connect to market server',
        'network'
      );
    }
    
    throw new MarketApiError(
      error.message || 'Unknown error occurred',
      'unknown'
    );
  }
}

/**
 * Fetch agent list from market with pagination and filters
 */
export async function fetchMarketAgentList(
  params?: MarketAgentListParams
): Promise<MarketAgentListResponse> {
  try {
    const url = API_ENDPOINTS.market.agents(params);
    const response = await fetchWithTimeout(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new MarketApiError(
        `Failed to fetch market agents: ${response.statusText}`,
        'server',
        response.status
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    log.error('Error fetching market agent list:', error);
    throw error;
  }
}

/**
 * Fetch agent detail by agent_id
 */
export async function fetchMarketAgentDetail(
  agentId: number
): Promise<MarketAgentDetail> {
  try {
    const url = API_ENDPOINTS.market.agentDetail(agentId);
    const response = await fetchWithTimeout(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new MarketApiError(
        `Failed to fetch market agent detail: ${response.statusText}`,
        'server',
        response.status
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    log.error('Error fetching market agent detail:', error);
    throw error;
  }
}

/**
 * Instantiate a new agent from a market template.
 *
 * Sends the Recipe variable values to the backend, which substitutes
 * `<<TO_CONFIG:xxx>>` placeholders, injects IndustryRule into the duty
 * prompt, and imports the agent tree into the current tenant.
 *
 * @param agentRepositoryId - The market template (agent_repository_id) to instantiate from.
 * @param variableValues - Recipe variable values keyed by variable key.
 * @param forceImport - When true, proceed even if precheck reports missing deps.
 * @returns `{ agent_id, precheck }` — agent_id is null when a precheck blocks.
 */
export async function instantiateMarketAgent(
  agentRepositoryId: string | number,
  variableValues: Record<string, any>,
  forceImport: boolean = false
): Promise<{ agent_id: number | null; precheck?: any; message?: string }> {
  try {
    const url = API_ENDPOINTS.market.instantiate(agentRepositoryId);
    const response = await fetchWithTimeout(
      url,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          variable_values: variableValues,
          force_import: forceImport,
        }),
      },
      30000 // instantiation may take a few seconds (skill import etc.)
    );

    if (!response.ok) {
      throw new MarketApiError(
        `Failed to instantiate agent: ${response.statusText}`,
        'server',
        response.status
      );
    }

    return await response.json();
  } catch (error) {
    log.error('Error instantiating market agent:', error);
    throw error;
  }
}

/**
 * Fetch all categories from market
 */
export async function fetchMarketCategories(): Promise<MarketCategory[]> {
  try {
    const url = API_ENDPOINTS.market.categories;
    const response = await fetchWithTimeout(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new MarketApiError(
        `Failed to fetch market categories: ${response.statusText}`,
        'server',
        response.status
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    log.error('Error fetching market categories:', error);
    throw error;
  }
}

/**
 * Fetch all tags from market
 */
export async function fetchMarketTags(): Promise<MarketTag[]> {
  try {
    const url = API_ENDPOINTS.market.tags;
    const response = await fetchWithTimeout(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new MarketApiError(
        `Failed to fetch market tags: ${response.statusText}`,
        'server',
        response.status
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    log.error('Error fetching market tags:', error);
    throw error;
  }
}

/**
 * Fetch MCP servers for specific agent
 */
export async function fetchMarketAgentMcpServers(
  agentId: number
): Promise<MarketMcpServer[]> {
  try {
    const url = API_ENDPOINTS.market.mcpServers(agentId);
    const response = await fetchWithTimeout(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new MarketApiError(
        `Failed to fetch agent MCP servers: ${response.statusText}`,
        'server',
        response.status
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    log.error('Error fetching agent MCP servers:', error);
    throw error;
  }
}

const marketService = {
  fetchMarketAgentList,
  fetchMarketAgentDetail,
  instantiateMarketAgent,
  fetchMarketCategories,
  fetchMarketTags,
  fetchMarketAgentMcpServers,
};

export default marketService;

