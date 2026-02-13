"use client";

import { useAuthenticationState } from "@/hooks/auth/useAuthenticationState";
import { useAuthenticationUI } from "@/hooks/auth/useAuthenticationUI";
import { AuthenticationContextType } from "@/types/auth";

/**
 * Custom hook for authentication management
 * Combines useAuthenticationState and useAuthenticationUI to provide full authentication functionality
 */
export function useAuthentication(): AuthenticationContextType {
  const authState = useAuthenticationState();
  // Pass auth state to useAuthenticationUI to avoid circular dependency
  const authUI = useAuthenticationUI({
    isAuthenticated: authState.isAuthenticated,
    isAuthChecking: authState.isAuthChecking,
    clearLocalSession: authState.clearLocalSession,
  });

  return {
    // Authentication state
    isAuthenticated: authState.isAuthenticated,
    isAuthChecking: authState.isAuthChecking,
    isLoading: authState.isLoading,
    session: authState.session,

    authServiceUnavailable: authState.authServiceUnavailable,

    // Methods
    login: authState.login,
    register: authState.register,
    logout: authState.logout,
    clearLocalSession: authState.clearLocalSession,
    revoke: authState.revoke,

    // UI state
    isLoginModalOpen: authUI.isLoginModalOpen,
    isRegisterModalOpen: authUI.isRegisterModalOpen,
    isAuthPromptModalOpen: authUI.isAuthPromptModalOpen,
    isSessionExpiredModalOpen: authUI.isSessionExpiredModalOpen,

    // UI methods
    openLoginModal: authUI.openLoginModal,
    closeLoginModal: authUI.closeLoginModal,

    openRegisterModal: authUI.openRegisterModal,
    closeRegisterModal: authUI.closeRegisterModal,

    openAuthPromptModal: authUI.openAuthPromptModal,
    closeAuthPromptModal: authUI.closeAuthPromptModal,

    openSessionExpiredModal: authUI.openSessionExpiredModal,
    closeSessionExpiredModal: authUI.closeSessionExpiredModal
  };
}
