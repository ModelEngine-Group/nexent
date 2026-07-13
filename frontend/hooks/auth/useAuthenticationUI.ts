"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { App } from "antd";
import { useTranslation } from "react-i18next";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { AUTH_EVENTS } from "@/const/auth";
import { getEffectiveRoutePath } from "@/lib/auth";
import { authEvents, authEventUtils } from "@/lib/authEvents";
import { authFlowState } from "@/lib/authFlow";
import { casService } from "@/services/casService";
import { AuthenticationUIReturn, RegisterModalOptions } from "@/types/auth";
import { oauthService } from "@/services/oauthService";
import log from "@/lib/logger";

/**
 * Custom hook for authentication UI management
 * Handles login/register modals, auth prompt modals, and session expired modal
 * Must be used within AuthenticationProvider
 */
export function useAuthenticationUI({
  isAuthenticated,
  isAuthChecking,
  clearLocalSession,
}: {
  isAuthenticated: boolean;
  isAuthChecking: boolean;
  clearLocalSession: () => void;
}): AuthenticationUIReturn {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isSpeedMode } = useDeployment();
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const effectivePath = pathname ? getEffectiveRoutePath(pathname) : "/";
  const isOAuthCompletePage = effectivePath === "/oauth/complete";
  const isSharePage = effectivePath.startsWith("/share/");
  const isRedirectingToCasRef = useRef(false);

  // UI state for modals - managed locally within the hook
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);
  const [registerModalOptions, setRegisterModalOptions] =
    useState<RegisterModalOptions | null>(null);
  const [isAuthPromptModalOpen, setIsAuthPromptModalOpen] = useState(false);
  const [isSessionExpiredModalOpen, setIsSessionExpiredModalOpen] =
    useState(false);
  const [ssoConfig, setSsoConfig] = useState<{ sso_enabled: boolean; sso_provider: string } | null>(null);

  useEffect(() => {
    const fetchSSOConfig = async () => {
      try {
        const config = await oauthService.getSSOConfig();
        setSsoConfig(config);
      } catch (error) {
        log.error("Failed to fetch SSO config:", error);
      }
    };
    fetchSSOConfig();
  }, []);

  const handleUnauthenticatedModalClose = () => {
    // Only emit back to home event and redirect if user is not authenticated
    if (!isAuthenticated && !isSpeedMode && !isSharePage) {
      // Emit event to notify SideNavigation to reset selected key
      authEventUtils.emitBackToHome();
      // Redirect to home page if not already there
      if (effectivePath !== "/" && !isOAuthCompletePage) {
        router.push("/");
      }
    }
  };

  // Modal control functions
  const openLoginModal = useCallback(() => setIsLoginModalOpen(true), []);

  const closeLoginModal = useCallback(() => {
    setIsLoginModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const openRegisterModal = useCallback((options?: RegisterModalOptions) => {
    setRegisterModalOptions(options || null);
    setIsRegisterModalOpen(true);
  }, []);

  const closeRegisterModal = useCallback(() => {
    setIsRegisterModalOpen(false);
    setRegisterModalOptions(null);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const redirectToCasIfForced = useCallback(
    async (redirect?: string): Promise<boolean> => {
      if (isRedirectingToCasRef.current) return true;
      if (authFlowState.isExplicitLogoutInProgress()) return true;

      const config = await casService.getConfig();
      if (authFlowState.isExplicitLogoutInProgress()) return true;
      if (!config.enabled || config.login_mode !== "force") return false;

      isRedirectingToCasRef.current = true;
      casService.startLogin(redirect);
      return true;
    },
    []
  );

  const openAuthPromptModal = useCallback(
    (redirect?: string) => {
      if (isSharePage) return;
      redirectToCasIfForced(redirect || effectivePath).then((redirected) => {
        if (!redirected) setIsAuthPromptModalOpen(true);
      });
    },
    [effectivePath, isSharePage, redirectToCasIfForced]
  );

  const closeAuthPromptModal = useCallback(() => {
    setIsAuthPromptModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const openSessionExpiredModal = useCallback(
    () => setIsSessionExpiredModalOpen(true),
    []
  );

  const closeSessionExpiredModal = useCallback(() => {
    clearLocalSession();
    setIsSessionExpiredModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const getOAuthErrorMessage = useCallback(
    (error: string) => {
      const key = `auth.oauthErrors.${error}`;
      const translated = t(key);
      if (translated !== key) {
        return translated;
      }
      return t("auth.oauthLoginFailedGeneric");
    },
    [t]
  );

  useEffect(() => {
    if (isSpeedMode) return;
    if (isSharePage) return;

    const handleSessionExpired = () => {
      // Prevent showing session expired modal when login/register modal is already open.
      // This avoids race conditions while the user is filling in an auth form.
      if (isLoginModalOpen || isRegisterModalOpen) {
        return;
      }

      redirectToCasIfForced(effectivePath).then((redirected) => {
        if (!redirected) setIsSessionExpiredModalOpen(true);
      });
    };

    const handleRegisterSuccess = () => {
      setIsRegisterModalOpen(false);
      setRegisterModalOptions(null);
    };

    const handlePostLogout = () => {
      openAuthPromptModal();
    };

    const cleanup = authEvents.on(
      AUTH_EVENTS.SESSION_EXPIRED,
      handleSessionExpired
    );
    const cleanupRegister = authEvents.on(
      AUTH_EVENTS.REGISTER_SUCCESS,
      handleRegisterSuccess
    );
    const cleanupPostLogout = authEvents.on(
      AUTH_EVENTS.POST_LOGOUT,
      handlePostLogout
    );

    return () => {
      cleanup();
      cleanupRegister();
      cleanupPostLogout();
    };
  }, [
    effectivePath,
    isSpeedMode,
    isSharePage,
    redirectToCasIfForced,
    isLoginModalOpen,
    isRegisterModalOpen,
    openAuthPromptModal,
  ]);

  // Auto-open login modal when returning from a failed OAuth redirect
  useEffect(() => {
    if (isSpeedMode) return;
    if (isOAuthCompletePage) return;
    if (isSharePage) return;
    if (isAuthChecking) return;
    if (isAuthenticated) {
      const oauthError = searchParams.get("oauth_error");
      if (oauthError) {
        message.error(getOAuthErrorMessage(oauthError));
        router.replace("/");
      }
      return;
    }

    const oauthError = searchParams.get("oauth_error");
    if (oauthError && !isLoginModalOpen) {
      setIsLoginModalOpen(true);
    }
  }, [
    searchParams,
    isAuthChecking,
    isAuthenticated,
    isSpeedMode,
    isLoginModalOpen,
    router,
    isOAuthCompletePage,
    isSharePage,
    message,
    getOAuthErrorMessage,
  ]);

  useEffect(() => {
    if (!isOAuthCompletePage) return;
    setIsAuthPromptModalOpen(false);
    setIsLoginModalOpen(false);
    setIsSessionExpiredModalOpen(false);
  }, [isOAuthCompletePage]);

  // Route guard for unauthenticated users - check when pathname changes
  // When SSO is enabled, skip showing auth prompt modal and let user browse freely
  useEffect(() => {
    if (isSpeedMode) return;
    if (isOAuthCompletePage) return;
    if (isSharePage) return;
    // Skip while checking auth state
    if (isAuthChecking) return;
    if (isAuthenticated) return;
    if (isSessionExpiredModalOpen) return;
    if (isLoginModalOpen) return;
    if (isRegisterModalOpen) return;
    let cancelled = false;

    // If SSO config is still loading or SSO is enabled, skip showing auth prompt modal
    if (ssoConfig === null || ssoConfig?.sso_enabled) {
      return;
    }

    openAuthPromptModal();

    redirectToCasIfForced(effectivePath).then((redirected) => {
      if (!cancelled && !redirected) {
        setIsAuthPromptModalOpen(true);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [
    effectivePath,
    isAuthenticated,
    isSpeedMode,
    isAuthChecking,
    isSessionExpiredModalOpen,
    isLoginModalOpen,
    isRegisterModalOpen,
    isOAuthCompletePage,
    isSharePage,
    redirectToCasIfForced,
    ssoConfig,
    openAuthPromptModal,
  ]);

  return {
    // Login/Register Modal
    isLoginModalOpen,
    openLoginModal,
    closeLoginModal,
    isRegisterModalOpen,
    registerModalOptions,
    openRegisterModal,
    closeRegisterModal,

    // Auth prompt modal
    isAuthPromptModalOpen,
    openAuthPromptModal,
    closeAuthPromptModal,

    // Session expired modal
    isSessionExpiredModalOpen,
    openSessionExpiredModal,
    closeSessionExpiredModal,
  };
}
