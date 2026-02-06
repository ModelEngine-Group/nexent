"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { authService } from "@/services/authService";
import { getSessionFromStorage, removeSessionFromStorage, checkSessionValid } from "@/lib/session";
import { Session, AuthenticationStateReturn, AuthenticationContextType } from "@/types/auth";
import { STATUS_CODES } from "@/const/auth";
import { authEventUtils } from "@/lib/authEvents";
import log from "@/lib/logger";

/**
 * Custom hook for authentication state management
 * Handles JWT tokens, login/logout, session restoration, and modal states
 */
export function useAuthenticationState(): AuthenticationStateReturn {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { isSpeedMode } = useDeployment();

  // Authentication state
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isAuthChecking, setIsAuthChecking] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [session, setSession] = useState<Session | null>(null);
  const [authServiceUnavailable, setAuthServiceUnavailable] =
    useState<boolean>(false);

  // Speed mode: skip authentication checks, consider user as authenticated
  useEffect(() => {
    if (isSpeedMode) {
      // In speed mode, user is considered authenticated without session
      setIsAuthenticated(true);
    } else {
      if (checkSessionValid()) {
        const storedSession = getSessionFromStorage();
        if (storedSession) {
          setSession(storedSession);
        }
        setIsAuthenticated(true);
      } else {
        setSession(null);
        setIsAuthenticated(false);
      }
    }
    setIsAuthChecking(false);
  }, [isSpeedMode]);

  const clearLocalSession = useCallback(() => {
    removeSessionFromStorage();
    setSession(null);
    setIsAuthenticated(false);
  }, []);

  // Login method
  const login = useCallback(
    async (
      email: string,
      password: string,
      options: { showSuccessMessage?: boolean } = {}
    ) => {
      const { showSuccessMessage = true } = options;

      setIsLoading(true);

      try {
        // First check auth service availability
        const isAuthServiceAvailable =
          await authService.checkAuthServiceAvailable();
        if (!isAuthServiceAvailable) {
          const error = new Error(t("auth.authServiceUnavailable"));
          (error as any).code = STATUS_CODES.AUTH_SERVICE_UNAVAILABLE;
          setAuthServiceUnavailable(true);
          throw error;
        }

        setAuthServiceUnavailable(false);

        const { data, error } = await authService.signIn(email, password);

        if (error) {
          log.error("Login failed: ", error.message);
          throw error;
        }

        if (data?.session) {
          // Update authentication state
          setSession(data.session);
          setIsAuthenticated(true);

          // Delay to ensure UI updates
          setTimeout(() => {
            if (showSuccessMessage) {
              message.success(t("auth.loginSuccess"));
            }

            authEventUtils.emitLoginSuccess();
          }, 150);
        }
      } catch (error: any) {
        log.error("Error during login process:", error.message);
        throw error;
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // Register method
  const register = useCallback(
    async (
      email: string,
      password: string,
      inviteCode?: string,
      withNewInvitation?: boolean
    ) => {
      setIsLoading(true);

      try {
        const { data, error } = await authService.signUp(
          email,
          password,
          inviteCode,
          withNewInvitation
        );

        if (error) {
          log.error("Registration failed: ", error.message);
          throw error;
        }

        if (data?.session) {
          setSession(data.session);
          setIsAuthenticated(true);

          setTimeout(() => {
            message.success(t("auth.registerSuccessAutoLogin"));

            // Emit register success event to close register modal
            authEventUtils.emitRegisterSuccess();
            // Emit login success event for permission fetching
            authEventUtils.emitLoginSuccess();
          }, 150);
        }
      } catch (error: any) {
        log.error("Error during registration process:", error.message);
        throw error;
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // Logout method
  const logout = useCallback(
    async (options: { silent?: boolean } = {}) => {
      const { silent = false } = options;

      try {
        setIsLoading(true);

        if (!silent) {
          // Call logout API
          await authService.signOut();
        }

        // Clear local session
        removeSessionFromStorage();
        setSession(null);
        setIsAuthenticated(false);

        if (!silent) {
          message.success(t("auth.logoutSuccess"));
        }

        // Emit logout event
        authEventUtils.emitLogout();
      } catch (error: any) {
        log.error("Logout failed:", error?.message || error);
        // Even if API call fails, clear local session
        removeSessionFromStorage();
        setSession(null);
        setIsAuthenticated(false);

        if (!silent) {
          message.error(t("auth.logoutFailed"));
        }
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // Revoke method
  const revoke = useCallback(async () => {
    try {
      setIsLoading(true);

      await authService.revoke();

      clearLocalSession();
      message.success(t("auth.revokeSuccess"));

      authEventUtils.emitLogout();
    } catch (error: any) {
      log.error("Revoke failed:", error?.message || error);
      message.error(t("auth.revokeFailed"));
    } finally {
      setIsLoading(false);
    }
  }, [clearLocalSession]);

  return {
    // Authentication state
    isAuthenticated,
    isAuthChecking,
    isLoading,
    session,
    authServiceUnavailable,

    // Methods
    login,
    register,
    logout,
    clearLocalSession,
    revoke
  };
}
