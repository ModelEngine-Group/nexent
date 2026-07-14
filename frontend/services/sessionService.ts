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

export type RefreshTokenResult =
  | { success: true; session: Session }
  | { success: false; error: string };

export const sessionService = {
  /**
   * Call backend refresh token API.
   * No need to pass refresh_token — it's in the HttpOnly cookie.
   * server.js intercepts this request and injects refresh_token into the body.
   */
  refreshToken: async (): Promise<RefreshTokenResult> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.user.refreshToken, {
        method: "POST",
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        return { success: false, error: body.detail || response.statusText };
      }

      const data = await response.json();
      const session = data.data?.session;
      if (session && session.expires_at) {
        return { success: true, session: { expires_at: session.expires_at } };
      }
      return { success: false, error: "Invalid session response" };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
};
