/**
 * 认证服务
 */
import { API_ENDPOINTS } from "@/services/api";
import { sessionService } from "@/services/sessionService";

import { Session, User, SessionResponse } from "@/types/auth";
import { STATUS_CODES } from "@/types/auth";

import { generateAvatarUrl, removeSessionFromStorage } from "@/lib/auth"
import { fetchWithAuth, getSessionFromStorage, saveSessionToStorage } from "@/lib/auth";


// Authentication service
export const authService = {
  // Get current session
  getSession: async (): Promise<Session | null> => {
    try {
      // Get session information from local storage
      const sessionObj = getSessionFromStorage();
      if (!sessionObj?.access_token) return null;
      
      // Check if the token is about to expire, if so, try to refresh
      const isTokenValid = await sessionService.checkAndRefreshToken();
      if (!isTokenValid) {
        console.warn("Token is invalid or refresh failed");
        // We do not immediately clear the session, but wait for subsequent operations to fail
      }
      
      try {
        // Verify if the session is valid
        const response = await fetchWithAuth(API_ENDPOINTS.user.session);
        
        // Check HTTP status code instead of data.code
        if (!response.ok) {
          console.warn("Session verification failed, HTTP status code:", response.status);
          
          // HTTP 401 means the token is expired or invalid
          if (response.status === STATUS_CODES.UNAUTHORIZED_HTTP) {
            return null;
          }
          
          // Other errors, possibly server issues, continue using local session
          console.warn("Backend session verification failed, but will continue using local session");
          return sessionObj;
        }
        
        const data = await response.json();
        
        // Update user information (possibly changed on the backend)
        if (data.data?.user) {
          sessionObj.user = {
            ...sessionObj.user,
            ...data.data.user,
            avatar_url: sessionObj.user.avatar_url // Keep avatar
          };
          
          // Update stored session
          saveSessionToStorage(sessionObj);
        }
        
        return sessionObj;
      } catch (error) {
        console.error("Error verifying session:", error);
        
        // Check if it is a TOKEN_EXPIRED error
        if (error instanceof Error && 'code' in error && (error as any).code === STATUS_CODES.TOKEN_EXPIRED) {
          return null;
        }
        
        // If it is another network error, do not immediately clear the session
        // It may be that the backend service is not started or temporarily unavailable
        console.warn("Backend session verification failed, but will continue using local session");
        return sessionObj;
      }
    } catch (error) {
      console.error("Failed to get session:", error);
      return null;
    }
  },

  // check auth service available
  checkAuthServiceAvailable: async (): Promise<boolean> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.serviceHealth, {method: 'GET'});
      
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
            data: data.data || null
          }
        };
      }
      
      // Generate avatar URL
      const avatar_url = generateAvatarUrl(email);
      
      // Build user object
      const user = {
        id: data.data.user.id,
        email: data.data.user.email,
        role: data.data.user.role,
        avatar_url,
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
          console.warn("Session not properly saved, retrying...");
          saveSessionToStorage(session);
        } else {
          console.debug("Session successfully saved to local storage");
        }
      }, 100);
      
      return { data: { session }, error: null };
    } catch (error) {
      console.error("Login failed:", error);
      return { 
        error: { 
          message: error instanceof Error ? error.message : "网络错误，请稍后重试",
          code: (error instanceof Error && 'code' in error) ? (error as any).code : STATUS_CODES.SERVER_ERROR
        }
      };
    }
  },

  // Register
  signUp: async (email: string, password: string, isAdmin?: boolean, inviteCode?: string): Promise<SessionResponse> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.signup, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ 
          email, 
          password, 
          is_admin: isAdmin || false,
          invite_code: inviteCode || null
        }),
      });
      
      const data = await response.json();
      
      // Check HTTP status code instead of data.code
      if (!response.ok) {
        return { 
          error: { 
            message: data.message || "注册失败",
            code: response.status,
            data: data.data || null
          }
        };
      }
      
      // Generate avatar URL
      const avatar_url = generateAvatarUrl(email);
      
      // Build user object
      const user: User = {
        id: data.data.user.id,
        email: data.data.user.email,
        role: data.data.user.role || "user",
        avatar_url,
      };
      
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
          return { data: { user, session: null }, error: null };
        }
        
        // Build complete session
        const session: Session = {
          user,
          access_token: loginData.data.session.access_token,
          refresh_token: loginData.data.session.refresh_token,
          expires_at: loginData.data.session.expires_at,
        };
        
        // Save session to local storage
        saveSessionToStorage(session);
        
        return { data: { user, session }, error: null };
      } else {
        // Use the session information returned by the registration interface
        const session: Session = {
          user,
          access_token: data.data.session.access_token,
          refresh_token: data.data.session.refresh_token,
          expires_at: data.data.session.expires_at,
        };
        
        // Save session to local storage
        saveSessionToStorage(session);
        
        return { data: { user, session }, error: null };
      }
    } catch (error) {
      console.error("Registration failed:", error);
      return { 
        error: { 
          message: "Network error, please try again later",
          code: STATUS_CODES.SERVER_ERROR
        }
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
      console.error("Logout failed:", error);
      
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
        console.warn("Failed to get user ID, HTTP status code:", response.status);
        return null;
      }
      
      const data = await response.json();
      
      if (!data.data) {
        return null;
      }
      
      return data.data.user_id;
    } catch (error) {
      console.error("Failed to get user ID:", error);
      return null;
    }
  },

  // Refresh token
  refreshToken: async (): Promise<boolean> => {
    return await sessionService.checkAndRefreshToken();
  }
}; 