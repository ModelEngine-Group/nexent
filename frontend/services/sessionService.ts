/**
 * Session management service
 * Pure API layer for session operations
 */

import { API_ENDPOINTS } from "./api";
import { fetchWithAuth } from "@/lib/auth";
import { Session } from "@/types/auth";

/**
 * Call backend refresh token API
 * @param refreshToken - refresh token string
 * @returns new session or null if failed
 */
export const sessionService = {
  refreshToken: async (refreshToken: string): Promise<Session | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.user.refreshToken, {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken })
      });

      if (!response.ok) {
        return null;
      }

      const data = await response.json();
      return data.data?.session || null;
    } catch {
      return null;
    }
  }
};
