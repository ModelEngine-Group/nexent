/**
 * Authentication service
 */
import { API_ENDPOINTS } from "@/services/api";
import { sessionService } from "@/services/sessionService";

import { Session, User, SessionResponse, AuthInfoResponse } from "@/types/auth";
import { STATUS_CODES } from "@/const/auth";

import { generateAvatarUrl } from "@/lib/auth";
import { fetchWithAuth } from "@/lib/auth";
import { removeSessionFromStorage, getSessionFromStorage, saveSessionToStorage } from "@/lib/session";
import log from "@/lib/logger";


// Authentication service
export const authService = {
  // Get current session
  getSession: async (): Promise<Session | null> => {
    try {
      // Get session information from local storage
      const sessionObj = getSessionFromStorage();
      if (!sessionObj?.access_token) return null;

      try {
        // Verify if the session is valid
        const response = await fetchWithAuth(API_ENDPOINTS.user.session);

        // Check HTTP status code instead of data.code
        if (!response.ok) {
          log.warn(
            "Session verification failed, HTTP status code:",
            response.status
          );

          // HTTP 401 means the token is expired or invalid
          if (response.status === STATUS_CODES.UNAUTHORIZED_HTTP) {
            return null;
          }

          // Other errors, possibly server issues, continue using local session
          log.warn(
            "Backend session verification failed, but will continue using local session"
          );
          return sessionObj;
        }

        return sessionObj;
      } catch (error) {
        log.error("Error verifying session:", error);

        // Check if it is a TOKEN_EXPIRED error
        if (
          error instanceof Error &&
          "code" in error &&
          (error as any).code === STATUS_CODES.TOKEN_EXPIRED
        ) {
          return null;
        }

        // If it is another network error, do not immediately clear the session
        // It may be that the backend service is not started or temporarily unavailable
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

  // Revoke (Delete account completely)
  revoke: async (): Promise<{ error: null }> => {
    try {
      // Call backend revoke API
      await fetchWithAuth(API_ENDPOINTS.user.revoke, {
        method: "POST",
      });
    } catch (error) {
      log.error("Account revoke failed:", error);
    } finally {
      // Always clear local session
      removeSessionFromStorage();
    }

    return { error: null };
  },

  // check auth service available
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

  // sign in
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

      // Check HTTP status code instead of data.code
      if (!response.ok) {
        return {
          error: {
            message: data.detail || data.message || "Login failed",
            code: response.status,
            data: data.data || null,
          },
        };
      }

      // Generate avatar URL
      const avatar_url = generateAvatarUrl(email);

      // Build user object
      const user = {
        id: data.data.user.id,
        email: data.data.user.email,
        role: data.data.user.role,
        avatarUrl: avatar_url,
      };

      // Build session object
      const session = {
        user,
        access_token: data.data.session.access_token,
        refresh_token: data.data.session.refresh_token,
        expires_at: data.data.session.expires_at,
      };

      // Save session to local storage
      saveSessionToStorage(session);

      // Verify if the session is properly saved, if not, try again
      setTimeout(() => {
        const savedSession = getSessionFromStorage();
        if (!savedSession || !savedSession.access_token) {
          log.warn("Session not properly saved, retrying...");
          saveSessionToStorage(session);
        } else {
          log.debug("Session successfully saved to local storage");
        }
      }, 100);

      return { data: { session }, error: null };
    } catch (error) {
      log.error("Login failed:", error);
      return {
        error: {
          message:
            error instanceof Error ? error.message : "网络错误，请稍后重试",
          code:
            error instanceof Error && "code" in error
              ? (error as any).code
              : STATUS_CODES.SERVER_ERROR,
        },
      };
    }
  },

  // Register
  signUp: async (
    email: string,
    password: string,
    inviteCode?: string,
    withNewInvitation?: boolean
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
          with_new_invitation: withNewInvitation || false,
        }),
      });

      const data = await response.json();

      // Check HTTP status code instead of data.code
      if (!response.ok) {
        return {
          error: {
            message: data.message || "注册失败",
            code: response.status,
            data: data.data || null,
          },
        };
      }


      // If the session information is not returned when registering, try to login
      if (!data.data.session || !data.data.session.access_token) {
        // Get login token
        const loginResponse = await fetch(API_ENDPOINTS.user.signin, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ email, password }),
        });

        const loginData = await loginResponse.json();

        if (!loginResponse.ok) {
          // Return the result with only the user and no session
          return { data: { session: null }, error: null };
        }

        // Build complete session
        const session: Session = {
          access_token: loginData.data.session.access_token,
          refresh_token: loginData.data.session.refresh_token,
          expires_at: loginData.data.session.expires_at,
        };

        // Save session to local storage
        saveSessionToStorage(session);

        return { data: { session }, error: null };
      } else {
        // Use the session information returned by the registration interface
        const session: Session = {
          access_token: data.data.session.access_token,
          refresh_token: data.data.session.refresh_token,
          expires_at: data.data.session.expires_at,
        };

        // Save session to local storage
        saveSessionToStorage(session);

        return { data: { session }, error: null };
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

  // Logout
  signOut: async (): Promise<{ error: null }> => {
    try {
      // Call the backend logout API
      await fetchWithAuth(API_ENDPOINTS.user.logout, {
        method: "POST",
      });

      // Clear local session regardless of success or failure
      removeSessionFromStorage();

      return { error: null };
    } catch (error) {
      log.error("Logout failed:", error);

      // Even if the API call fails, clear the local session
      removeSessionFromStorage();

      return { error: null };
    }
  },

  // Get current user ID
  getCurrentUserId: async (): Promise<string | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.user.currentUserId);

      // Check HTTP status code instead of data.code
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
      // Check HTTP status code instead of data.code
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
  // Refresh token
  refreshToken: async (): Promise<boolean> => {
    const sessionObj = getSessionFromStorage();
    if (!sessionObj?.refresh_token) return false;

    const newSession = await sessionService.refreshToken(sessionObj.refresh_token);
    if (newSession) {
      saveSessionToStorage(newSession);
      return true;
    }
    return false;
  },
}; 