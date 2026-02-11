"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { AUTH_EVENTS } from "@/const/auth";
import { getEffectiveRoutePath } from "@/lib/auth";
import { authEvents, authEventUtils } from "@/lib/authEvents";
import { AuthenticationUIReturn } from "@/types/auth";
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
  const { t } = useTranslation("common");
  const { isSpeedMode } = useDeployment();

  // UI state for modals - managed locally within the hook
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);
  const [isAuthPromptModalOpen, setIsAuthPromptModalOpen] = useState(false);
  const [isSessionExpiredModalOpen, setIsSessionExpiredModalOpen] = useState(false);

  const handleUnauthenticatedModalClose = (() => {
    // Only emit back to home event and redirect if user is not authenticated
    if (!isAuthenticated && !isSpeedMode) {
        
      // Emit event to notify SideNavigation to reset selected key
      authEventUtils.emitBackToHome();
      // Redirect to home page if not already there
      const effectivePath = pathname ? getEffectiveRoutePath(pathname) : "/";
      if (effectivePath !== "/") {
        router.push("/");
      }
    }
  });

  // Modal control functions
  const openLoginModal = useCallback(() => setIsLoginModalOpen(true), []);

  const closeLoginModal = useCallback(() => {
    setIsLoginModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const openRegisterModal = useCallback(() => setIsRegisterModalOpen(true), []);

  const closeRegisterModal = useCallback(() => {
    setIsRegisterModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const openAuthPromptModal = useCallback(() => setIsAuthPromptModalOpen(true), []);

  const closeAuthPromptModal = useCallback(() => {
    setIsAuthPromptModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  const openSessionExpiredModal = useCallback(() => setIsSessionExpiredModalOpen(true), []);

  const closeSessionExpiredModal = useCallback(() => {
    clearLocalSession();
    setIsSessionExpiredModalOpen(false);
    handleUnauthenticatedModalClose();
  }, [handleUnauthenticatedModalClose]);

  /**
   * Check if current path is home page
   * Home page paths: "/", "/zh", "/en"
   */
  const isLocaleHomePath = (path?: string | null) => {
    if (!path) return false;
    const segments = path.split("/").filter(Boolean);
    return segments.length <= 1;
  };

  useEffect(() => {
    if (isSpeedMode) return;

    const handleSessionExpired = () => {
      setIsSessionExpiredModalOpen(true);
    };

    const handleRegisterSuccess = () => {
      setIsRegisterModalOpen(false);
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
  }, [isSpeedMode, setIsSessionExpiredModalOpen]);



  // Route guard for unauthenticated users - check when pathname changes
  useEffect(() => {
    if (isSpeedMode) return;
    // Skip while checking auth state
    if (isAuthChecking) return;
    // Skip if user is authenticated
    if (isAuthenticated) return;
    // Skip if session expired modal is already showing (avoid duplicate modals)
    if (isSessionExpiredModalOpen) return;
    if (isLoginModalOpen) return;
    if (isRegisterModalOpen) return;
    // Skip if already on home page
    if (isLocaleHomePath(pathname)) return;

    // For unauthenticated users accessing protected routes, show auth prompt
    const effectivePath = getEffectiveRoutePath(pathname);
    if (effectivePath !== "/") {
      openAuthPromptModal();
    }
  }, [pathname, isAuthenticated, isSpeedMode, isAuthChecking, isSessionExpiredModalOpen, openAuthPromptModal]);


  return {
    // Login/Register Modal
    isLoginModalOpen,
    openLoginModal,
    closeLoginModal,
    isRegisterModalOpen,
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
