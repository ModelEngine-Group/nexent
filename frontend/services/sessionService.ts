/**
 * Session management service
 * Pure API layer for session operations
 *
 * After HttpOnly cookie migration:
 * - refresh_token is sent automatically via HttpOnly cookie
 * - server.js extracts it and forwards to backend in the request body
 * - New tokens are set as cookies by server.js in the response
 */

import { API_ENDPOINTS } from "./api";
import { fetchWithAuth } from "@/lib/auth";
import { Session } from "@/types/auth";

export const sessionService = {
  /**
   * Call backend refresh token API.
   * No need to pass refresh_token — it's in the HttpOnly cookie.
   * server.js intercepts this request and injects refresh_token into the body.
   * @returns new session (expires_at only) or null if failed
   */
  refreshToken: async (): Promise<Session | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.user.refreshToken, {
        method: "POST",
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        return null;
      }

      const data = await response.json();
      const session = data.data?.session;
      if (session && session.expires_at) {
        return { expires_at: session.expires_at };
      }
      return null;
    } catch {
      return null;
    }
  },
};
