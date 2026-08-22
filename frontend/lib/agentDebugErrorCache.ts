/**
 * Agent debug error cache utilities
 * Persists debug errors in localStorage so users can see previous errors
 * when re-entering debug mode for the same agent
 */

const DEBUG_ERROR_CACHE_KEY = "nexent_agent_debug_errors";

export interface DebugErrorInfo {
  agentId: number;
  errorMessage: string;
  timestamp: number;
}

/**
 * Get cached debug errors for a specific agent
 * @param agentId The agent ID to get cached errors for
 * @returns The cached error message or null if no cached error
 */
export function getCachedDebugError(agentId: number): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const cachedData = localStorage.getItem(DEBUG_ERROR_CACHE_KEY);
    if (!cachedData) {
      return null;
    }

    const errors: DebugErrorInfo[] = JSON.parse(cachedData);
    const agentError = errors.find((e) => e.agentId === agentId);

    return agentError ? agentError.errorMessage : null;
  } catch (error) {
    console.warn("Failed to read cached debug error:", error);
    return null;
  }
}

/**
 * Cache a debug error for a specific agent
 * @param agentId The agent ID
 * @param errorMessage The error message to cache
 */
export function cacheDebugError(agentId: number, errorMessage: string): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const cachedData = localStorage.getItem(DEBUG_ERROR_CACHE_KEY);
    let errors: DebugErrorInfo[] = cachedData ? JSON.parse(cachedData) : [];

    // Remove existing error for this agent if any
    errors = errors.filter((e) => e.agentId !== agentId);

    // Add new error
    errors.push({
      agentId,
      errorMessage,
      timestamp: Date.now(),
    });

    // Keep only the most recent 10 errors to avoid localStorage bloat
    if (errors.length > 10) {
      errors = errors.slice(-10);
    }

    localStorage.setItem(DEBUG_ERROR_CACHE_KEY, JSON.stringify(errors));
  } catch (error) {
    console.warn("Failed to cache debug error:", error);
  }
}

/**
 * Clear cached debug error for a specific agent
 * @param agentId The agent ID to clear cached error for
 */
export function clearCachedDebugError(agentId: number): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const cachedData = localStorage.getItem(DEBUG_ERROR_CACHE_KEY);
    if (!cachedData) {
      return;
    }

    const errors: DebugErrorInfo[] = JSON.parse(cachedData);
    const filteredErrors = errors.filter((e) => e.agentId !== agentId);

    if (filteredErrors.length === 0) {
      localStorage.removeItem(DEBUG_ERROR_CACHE_KEY);
    } else {
      localStorage.setItem(DEBUG_ERROR_CACHE_KEY, JSON.stringify(filteredErrors));
    }
  } catch (error) {
    console.warn("Failed to clear cached debug error:", error);
  }
}

/**
 * Clear all cached debug errors
 */
export function clearAllCachedDebugErrors(): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    localStorage.removeItem(DEBUG_ERROR_CACHE_KEY);
  } catch (error) {
    console.warn("Failed to clear all cached debug errors:", error);
  }
}
