/**
 * Session management service
 */

import { TOKEN_REFRESH_CD } from "@/const/constants";
import { API_ENDPOINTS } from "./api";

import { fetchWithAuth, saveSessionToStorage, removeSessionFromStorage, getSessionFromStorage } from "@/lib/auth";
import log from "@/lib/logger";

// Record the time of the last token refresh
let lastTokenRefreshTime = 0;

/**
 * Check and refresh token (if needed)
 */
export const sessionService = {
  checkAndRefreshToken: async (): Promise<boolean> => {
    try {
      const sessionObj = getSessionFromStorage();
      if (!sessionObj) return false;
      
      const now = Date.now();
      
      // Check if the token is in the refresh cooldown period
      const timeSinceLastRefresh = now - lastTokenRefreshTime;
      if (timeSinceLastRefresh < TOKEN_REFRESH_CD) {
        return true; // In cooldown period, default token is valid
      }
      
      // Check if the token has expired
      const expiresAt = sessionObj.expires_at * 1000; // Convert to milliseconds
      if (expiresAt > now) {
        // Token not expired, try to refresh
        // Update the last refresh time, even if it hasn't succeeded, record the attempt time to avoid frequent requests
        lastTokenRefreshTime = now;
        
        // Call the refresh token API
        const response = await fetchWithAuth(API_ENDPOINTS.user.refreshToken, {
          method: "POST",
          body: JSON.stringify({
            refresh_token: sessionObj.refresh_token
          })
        });
        
        // Check HTTP status code instead of data.code
        if (!response.ok) {
          log.warn("Token refresh failed, HTTP status code:", response.status);
          
          // HTTP 401 means the token is expired
          if (response.status === 401) {
            removeSessionFromStorage();
          }
          
          return false;
        }
        
        const data = await response.json();
        
        if (data.data?.session) {
          // Update the session information in local storage
          const updatedSession = {
            ...sessionObj,
            access_token: data.data.session.access_token,
            refresh_token: data.data.session.refresh_token,
            expires_at: data.data.session.expires_at,
          };
          
          saveSessionToStorage(updatedSession);
          return true;
        } else {
          log.warn("Token refresh failed: incorrect response data format");
          return false;
        }
      } else {
        // Token expired, clear the session
        log.warn("Token expired");
        removeSessionFromStorage();
        return false;
      }
    } catch (error) {
      log.error("Check token status failed:", error);
      return false;
    }
  }
}; 