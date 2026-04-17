/**
 * Agent generation cache utilities for persisting generation state across agent switches
 * Caches the streaming generation content to localStorage so users can resume viewing
 * when switching back to the same agent
 */

const GENERATION_CACHE_PREFIX = "nexent_agent_generation_cache_";

/**
 * Cache structure for agent generation content
 */
export interface AgentGenerationCache {
  /** The agent ID this cache belongs to (0 for create mode) */
  agentId: number;
  /** Cache timestamp for expiry checking */
  timestamp: number;
  /** Cache expiry time in milliseconds (default 30 minutes) */
  expiryMs: number;
  /** Whether a generation is currently in progress */
  isGenerating: boolean;
  /** Business description used for generation */
  businessDescription: string;
  /** Business logic model ID */
  businessLogicModelId: number;
  /** Business logic model name */
  businessLogicModelName: string;
  /** Generated duty prompt */
  dutyPrompt: string;
  /** Generated constraint prompt */
  constraintPrompt: string;
  /** Generated few-shots prompt */
  fewShotsPrompt: string;
  /** Generated agent name */
  agentName: string;
  /** Generated agent display name */
  agentDisplayName: string;
  /** Generated agent description */
  agentDescription: string;
}

/**
 * Default cache values
 */
const DEFAULT_CACHE: AgentGenerationCache = {
  agentId: 0,
  timestamp: 0,
  expiryMs: 30 * 60 * 1000, // 30 minutes
  isGenerating: false,
  businessDescription: "",
  businessLogicModelId: 0,
  businessLogicModelName: "",
  dutyPrompt: "",
  constraintPrompt: "",
  fewShotsPrompt: "",
  agentName: "",
  agentDisplayName: "",
  agentDescription: "",
};

/**
 * Get the storage key for a specific agent
 * @param agentId - The agent ID (use 0 for create mode)
 */
export function getCacheKey(agentId: number): string {
  return `${GENERATION_CACHE_PREFIX}${agentId}`;
}

/**
 * Check if a cache has expired
 */
export function isCacheExpired(cache: AgentGenerationCache): boolean {
  if (cache.timestamp === 0) return true;
  return Date.now() - cache.timestamp > cache.expiryMs;
}

/**
 * Get generation cache for a specific agent
 * @param agentId - The agent ID (use 0 for create mode)
 * @returns The cached generation content or null if not found/expired
 */
export function getAgentGenerationCache(agentId: number): AgentGenerationCache | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    const cached = localStorage.getItem(getCacheKey(agentId));
    if (!cached) return null;

    const parsed: AgentGenerationCache = JSON.parse(cached);
    if (isCacheExpired(parsed)) {
      // Clean up expired cache
      localStorage.removeItem(getCacheKey(agentId));
      return null;
    }

    return parsed;
  } catch (error) {
    console.warn('Failed to read agent generation cache:', error);
    return null;
  }
}

/**
 * Save generation cache for a specific agent
 * @param agentId - The agent ID (use 0 for create mode)
 * @param cache - The cache data to save
 */
export function saveAgentGenerationCache(
  agentId: number,
  cache: Partial<AgentGenerationCache>
): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    // Get existing cache or default
    const existing = getAgentGenerationCache(agentId);
    const merged: AgentGenerationCache = {
      ...DEFAULT_CACHE,
      ...existing,
      ...cache,
      agentId,
      timestamp: Date.now(),
    };

    localStorage.setItem(getCacheKey(agentId), JSON.stringify(merged));
  } catch (error) {
    console.warn('Failed to save agent generation cache:', error);
  }
}

/**
 * Update specific fields in the generation cache
 * Used during streaming to incrementally save content
 * @param agentId - The agent ID (use 0 for create mode)
 * @param updates - The fields to update
 */
export function updateAgentGenerationCache<K extends keyof AgentGenerationCache>(
  agentId: number,
  updates: Pick<AgentGenerationCache, K>
): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    const existing = getAgentGenerationCache(agentId);
    const updated: AgentGenerationCache = {
      ...DEFAULT_CACHE,
      ...existing,
      ...updates,
      agentId,
      timestamp: Date.now(),
    };

    localStorage.setItem(getCacheKey(agentId), JSON.stringify(updated));
  } catch (error) {
    console.warn('Failed to update agent generation cache:', error);
  }
}

/**
 * Mark generation as in-progress in cache
 * @param agentId - The agent ID (use 0 for create mode)
 * @param isGenerating - Whether generation is in progress
 * @param businessInfo - Optional business info to cache
 */
export function setAgentGenerationStatus(
  agentId: number,
  isGenerating: boolean,
  businessInfo?: {
    businessDescription: string;
    businessLogicModelId: number;
    businessLogicModelName: string;
  }
): void {
  const updates = { isGenerating, ...businessInfo };
  updateAgentGenerationCache(agentId, updates);
}

/**
 * Save generated content to cache (called on each streaming update)
 * @param agentId - The agent ID (use 0 for create mode)
 * @param field - Which field is being updated
 * @param content - The content value
 */
export function saveGeneratedField<
  K extends keyof Pick<
    AgentGenerationCache,
    'dutyPrompt' | 'constraintPrompt' | 'fewShotsPrompt' | 'agentName' | 'agentDisplayName' | 'agentDescription'
  >
>(
  agentId: number,
  field: K,
  content: AgentGenerationCache[K]
): void {
  const updates = { [field]: content } as Pick<AgentGenerationCache, K>;
  updateAgentGenerationCache(agentId, updates);
}

/**
 * Clear generation cache for a specific agent
 * Call this when generation completes successfully or is discarded
 * @param agentId - The agent ID (use 0 for create mode)
 */
export function clearAgentGenerationCache(agentId: number): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    localStorage.removeItem(getCacheKey(agentId));
  } catch (error) {
    console.warn('Failed to clear agent generation cache:', error);
  }
}

/**
 * Clear all agent generation caches
 * Useful when user logs out or session ends
 */
export function clearAllGenerationCaches(): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    const keys = Object.keys(localStorage).filter((key) =>
      key.startsWith(GENERATION_CACHE_PREFIX)
    );
    keys.forEach((key) => localStorage.removeItem(key));
  } catch (error) {
    console.warn('Failed to clear all generation caches:', error);
  }
}

/**
 * Clear expired generation caches
 * Call this on mount instead of blindly clearing all isGenerating caches
 */
export function clearExpiredGenerationCaches(): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    const keys = Object.keys(localStorage).filter((key) =>
      key.startsWith(GENERATION_CACHE_PREFIX)
    );

    for (const key of keys) {
      try {
        const cached = localStorage.getItem(key);
        if (!cached) continue;

        const parsed: AgentGenerationCache = JSON.parse(cached);
        if (isCacheExpired(parsed)) {
          localStorage.removeItem(key);
        }
      } catch {
        // Ignore parse errors for individual entries
      }
    }
  } catch (error) {
    console.warn('Failed to clear expired generation caches:', error);
  }
}