"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { App } from "antd";
import { useTranslation } from "react-i18next";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { AUTH_EVENTS } from "@/const/auth";
import { getEffectiveRoutePath } from "@/lib/auth";
import { authEvents, authEventUtils } from "@/lib/authEvents";
import { forcedLoginService } from "@/services/forcedLoginService";
import { AuthenticationUIReturn, RegisterModalOptions } from "@/types/auth";

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

  // UI state for modals - managed locally within the hook
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);
  const [registerModalOptions, setRegisterModalOptions] =
    useState<RegisterModalOptions | null>(null);
  const [isAuthPromptModalOpen, setIsAuthPromptModalOpen] = useState(false);
  const [isSessionExpiredModalOpen, setIsSessionExpiredModalOpen] =
    useState(false);

  const handleUnauthenticatedModalClose = useCallback(() => {
    // Only emit back to home event and redirect if user is not authenticated
    if (!isAuthenticated && !isSpeedMode && !isSharePage) {
      // Emit event to notify SideNavigation to reset selected key
      authEventUtils.emitBackToHome();
      // Redirect to home page if not already there
      if (effectivePath !== "/" && !isOAuthCompletePage) {
        router.push("/");
      }
    }
  }, [
    effectivePath,
    isAuthenticated,
    isOAuthCompletePage,
    isSharePage,
    isSpeedMode,
    router,
  ]);

  const redirectToForcedLogin = useCallback(
    (redirect?: string): Promise<boolean> =>
      forcedLoginService.redirectIfNeeded(redirect),
    []
  );

  // Modal control functions
  const openLoginModal = useCallback(() => {
    if (isSharePage) {
      setIsLoginModalOpen(true);
      return;
    }

    redirectToForcedLogin(effectivePath).then((redirected) => {
      if (!redirected) setIsLoginModalOpen(true);
    });
  }, [effectivePath, isSharePage, redirectToForcedLogin]);

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

  const openAuthPromptModal = useCallback(
    (redirect?: string) => {
      if (isSharePage) return;
      redirectToForcedLogin(redirect || effectivePath).then((redirected) => {
        if (!redirected) setIsAuthPromptModalOpen(true);
      });
    },
    [effectivePath, isSharePage, redirectToForcedLogin]
  );

  const closeAuthPromptModal = useCallback(() => {
    setIsAuthPromptModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const openSessionExpiredModal = useCallback(() => {
    if (isSharePage) return;
    redirectToForcedLogin(effectivePath).then((redirected) => {
      if (!redirected) setIsSessionExpiredModalOpen(true);
    });
  }, [effectivePath, isSharePage, redirectToForcedLogin]);

  const closeSessionExpiredModal = useCallback(() => {
    clearLocalSession();
    setIsSessionExpiredModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [clearLocalSession, handleUnauthenticatedModalClose]);

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

      openSessionExpiredModal();
    };

    const handleRegisterSuccess = () => {
      setIsRegisterModalOpen(false);
      setRegisterModalOptions(null);
    };

    // Add event listener using type-safe auth events
    const cleanup = authEvents.on(
      AUTH_EVENTS.SESSION_EXPIRED,
      handleSessionExpired
    );
    const cleanupRegister = authEvents.on(
      AUTH_EVENTS.REGISTER_SUCCESS,
      handleRegisterSuccess
    );

    // Return cleanup function
    return () => {
      cleanup();
      cleanupRegister();
    };
  }, [
    effectivePath,
    isSpeedMode,
    isSharePage,
    openSessionExpiredModal,
    isLoginModalOpen,
    isRegisterModalOpen,
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
      forcedLoginService.suppressOAuthAutoLogin();
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
  useEffect(() => {
    if (isSpeedMode) return;
    if (isOAuthCompletePage) return;
    if (isSharePage) return;
    // Skip while checking auth state
    if (isAuthChecking) return;
    // Skip if user is authenticated
    if (isAuthenticated) return;
    // Skip if session expired modal is already showing (avoid duplicate modals)
    if (isSessionExpiredModalOpen) return;
    if (isLoginModalOpen) return;
    if (isRegisterModalOpen) return;
    let cancelled = false;

    redirectToForcedLogin(effectivePath).then((redirected) => {
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
    redirectToForcedLogin,
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
