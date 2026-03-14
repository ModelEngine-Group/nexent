/**
 * Authentication service
 *
 * After HttpOnly cookie migration:
 * - Tokens are managed by server.js via HttpOnly cookies (Set-Cookie on login/refresh)
 * - Frontend only stores user display info in localStorage
 * - expires_at is readable from a non-HttpOnly cookie
 */
import { API_ENDPOINTS } from "@/services/api";
import { sessionService } from "@/services/sessionService";

import { Session, SessionResponse, AuthInfoResponse } from "@/types/auth";
import { STATUS_CODES } from "@/const/auth";

import { generateAvatarUrl } from "@/lib/auth";
import { fetchWithAuth } from "@/lib/auth";
import {
  removeSessionFromStorage,
  getSessionFromStorage,
  saveUserToStorage,
  removeUserFromStorage,
  checkSessionValid,
} from "@/lib/session";
import log from "@/lib/logger";


export const authService = {
  getSession: async (): Promise<Session | null> => {
    try {
      const sessionObj = getSessionFromStorage();
      if (!sessionObj) return null;

      try {
        const response = await fetchWithAuth(API_ENDPOINTS.user.session);

        if (!response.ok) {
          log.warn(
            "Session verification failed, HTTP status code:",
            response.status
          );

          if (response.status === STATUS_CODES.UNAUTHORIZED_HTTP) {
            return null;
          }

          log.warn(
            "Backend session verification failed, but will continue using local session"
          );
          return sessionObj;
        }

        return sessionObj;
      } catch (error) {
        log.error("Error verifying session:", error);

        if (
          error instanceof Error &&
          "code" in error &&
          (error as any).code === STATUS_CODES.TOKEN_EXPIRED
        ) {
          return null;
        }

        log.warn(
          "Backend session verification failed, but will continue using local session"
        );
        return sessionObj;
      }
    } catch (error) {
      log.error("Failed to get session:", error);
      return null;
    }
  },

  revoke: async (): Promise<{ error: null }> => {
    try {
      await fetchWithAuth(API_ENDPOINTS.user.revoke, {
        method: "POST",
      });
    } catch (error) {
      log.error("Account revoke failed:", error);
    } finally {
      removeSessionFromStorage();
    }

    return { error: null };
  },

  checkAuthServiceAvailable: async (): Promise<boolean> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.serviceHealth, {
        method: "GET",
      });

      return response.status === STATUS_CODES.SUCCESS;
    } catch (error) {
      return false;
    }
  },

  signIn: async (email: string, password: string): Promise<SessionResponse> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.signin, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email,
          password,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        return {
          error: {
            message: data.detail || data.message || "Login failed",
            code: response.status,
            data: data.data || null,
          },
        };
      }

      const avatar_url = generateAvatarUrl(email);

      const user = {
        id: data.data.user.id,
        email: data.data.user.email,
        role: data.data.user.role,
        avatarUrl: avatar_url,
      };

      // Save user display info to localStorage
      saveUserToStorage(user);

      // Tokens are already set as HttpOnly cookies by server.js.
      // Build session from the expires_at returned in the (sanitized) response.
      const session: Session = {
        expires_at: data.data.session.expires_at,
      };

      return { data: { session, user }, error: null };
    } catch (error) {
      log.error("Login failed:", error);
      return {
        error: {
          message:
            error instanceof Error ? error.message : "Network error, please try again later",
          code:
            error instanceof Error && "code" in error
              ? (error as any).code
              : STATUS_CODES.SERVER_ERROR,
        },
      };
    }
  },

  signUp: async (
    email: string,
    password: string,
    inviteCode?: string,
    autoLogin: boolean = true
  ): Promise<SessionResponse> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.signup, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email,
          password,
          invite_code: inviteCode || null,
          auto_login: autoLogin,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        return {
          error: {
            message: data.message || "Registration failed",
            code: response.status,
            data: data.data || null,
          },
        };
      }

      if (!autoLogin) {
        return { data: { session: null }, error: null };
      }

      const avatar_url = generateAvatarUrl(email);

      // If no session returned from signup, try explicit sign-in
      if (!data.data.session || !data.data.session.expires_at) {
        const loginResponse = await fetch(API_ENDPOINTS.user.signin, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ email, password }),
        });

        const loginData = await loginResponse.json();

        if (!loginResponse.ok) {
          return { data: { session: null }, error: null };
        }

        const user = {
          id: loginData.data.user.id,
          email: loginData.data.user.email,
          role: loginData.data.user.role,
          avatarUrl: avatar_url,
        };
        saveUserToStorage(user);

        const session: Session = {
          expires_at: loginData.data.session.expires_at,
        };

        return { data: { session, user }, error: null };
      } else {
        const userData = data.data.user;
        const user = {
          id: userData?.id || "",
          email: userData?.email || email,
          role: userData?.role || "USER",
          avatarUrl: avatar_url,
        };
        saveUserToStorage(user);

        const session: Session = {
          expires_at: data.data.session.expires_at,
        };

        return { data: { session, user }, error: null };
      }
    } catch (error) {
      log.error("Registration failed:", error);
      return {
        error: {
          message: "Network error, please try again later",
          code: STATUS_CODES.SERVER_ERROR,
        },
      };
    }
  },

  signOut: async (): Promise<{ error: null }> => {
    try {
      await fetchWithAuth(API_ENDPOINTS.user.logout, {
        method: "POST",
      });

      // server.js clears HttpOnly cookies; clear local user info
      removeSessionFromStorage();

      return { error: null };
    } catch (error) {
      log.error("Logout failed:", error);

      removeSessionFromStorage();

      return { error: null };
    }
  },

  getCurrentUserId: async (): Promise<string | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.user.currentUserId);

      if (!response.ok) {
        log.warn("Failed to get user ID, HTTP status code:", response.status);
        return null;
      }

      const data = await response.json();

      if (!data.data) {
        return null;
      }

      return data.data.user_id;
    } catch (error) {
      log.error("Failed to get user ID:", error);
      return null;
    }
  },

  getCurrentUserInfo: async (): Promise<AuthInfoResponse | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.user.currentUserInfo);
      if (!response.ok) {
        log.warn("Failed to get user Info, HTTP status code:", response.status);
        return null;
      }

      const data = await response.json();

      if (!data.data) {
        return null;
      }
      const userData = {
        user: {
          id: data.data.user.user_id,
          groupIds: data.data.user.group_ids,
          tenantId: data.data.user.tenant_id,
          email: data.data.user.user_email,
          role: data.data.user.user_role,
          avatarUrl: data.data.user.avatarUrl,
          permissions: data.data.user.permissions.map((permission:string) => permission.toLowerCase()),
          accessibleRoutes: data.data.user.accessibleRoutes.map((router:string) => router.toLowerCase()),
        }
      }
      return userData as AuthInfoResponse;
    } catch (error) {
      log.error("Failed to get user Info:", error);
      return null;
    }
  },

  refreshToken: async (): Promise<boolean> => {
    if (!checkSessionValid()) return false;

    const newSession = await sessionService.refreshToken();
    return newSession !== null;
  },
};
