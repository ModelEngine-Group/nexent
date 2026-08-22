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
  fetchMarketCategories,
  fetchMarketTags,
  fetchMarketAgentMcpServers,
};

export default marketService;

