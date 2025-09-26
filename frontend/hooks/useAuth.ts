"use client"

import { useState, useEffect, useContext, createContext, type ReactNode } from "react"
import { usePathname } from "next/navigation"
import { useTranslation } from "react-i18next"

import { App } from "antd"
import { USER_ROLES } from "@/const/modelConfig"

import { authService } from "@/services/authService"
import { configService } from "@/services/configService"
import { API_ENDPOINTS } from "@/services/api"
import { User, AuthContextType } from "@/types/auth"
import { EVENTS, STATUS_CODES } from "@/const/auth"
import { getSessionFromStorage } from "@/lib/auth"
import log from "@/lib/logger"

// Create auth context
const AuthContext = createContext<AuthContextType | undefined>(undefined)

// Auth provider component
export function AuthProvider({ children }: { children: (value: AuthContextType) => ReactNode }) {
  const { t } = useTranslation('common');
  const { message } = App.useApp();
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false)
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false)
  const [isFromSessionExpired, setIsFromSessionExpired] = useState(false)
  const [shouldCheckSession, setShouldCheckSession] = useState(false)
  const [authServiceUnavailable, setAuthServiceUnavailable] = useState(false)
  const [isSpeedMode, setIsSpeedMode] = useState(false)
  const [isReady, setIsReady] = useState(false)
  const pathname = usePathname()

  // Check auth service availability
  const checkAuthService = async () => {
    const isAvailable = await authService.checkAuthServiceAvailable()
    setAuthServiceUnavailable(!isAvailable)
    return isAvailable
  }

  // When login or register modal is opened, check auth service availability
  useEffect(() => {
    if (isLoginModalOpen || isRegisterModalOpen) {
      checkAuthService()
    }
  }, [isLoginModalOpen, isRegisterModalOpen])

  // Check deployment version and handle speed mode
  const checkDeploymentVersion = async () => {
    try {
      setIsReady(false);
      const response = await fetch(API_ENDPOINTS.tenantConfig.deploymentVersion);
      if (response.ok) {
        const data = await response.json();
        const version = data.content?.deployment_version || data.deployment_version;
        
        setIsSpeedMode(version === 'speed');
        
        // If in speed mode and no user exists, perform auto login
        if (version === 'speed' && !user) {
          await performAutoLogin();
        }
      }
    } catch (error) {
      log.error('Failed to check deployment version:', error);
      setIsSpeedMode(false);
    } finally {
      setIsReady(true);
    }
  };

  // Auto login function (for speed mode)
  const performAutoLogin = async () => {
    try {
      // Use mock credentials for auto login
      await login('mock@example.com', 'mockpassword', false);
    } catch (error) {
      log.error('Auto-login failed:', error);
    }
  };

  // When initializing, check user session (only read from local storage, not request backend)
  useEffect(() => {
    const syncUserFromLocalStorage = () => {
      const storedSession = typeof window !== "undefined" ? localStorage.getItem("session") : null;
      if (storedSession) {
        try {
          const session = JSON.parse(storedSession);
          if (session?.user) {
            const safeUser: User = {
              id: session.user.id,
              email: session.user.email,
              role: session.user.role === USER_ROLES.ADMIN ? USER_ROLES.ADMIN : USER_ROLES.USER,
              avatar_url: session.user.avatar_url
            };
            setUser(safeUser);
            setShouldCheckSession(true); // When there is a user, enable session check
            return;
          }
        } catch (e) {
          // ignore parse error
        }
      }
      setUser(null);
      setShouldCheckSession(false); // When there is no user, disable session check
    };

    setIsLoading(true);
    syncUserFromLocalStorage();
    setIsLoading(false);

    // Listen to local session change
    const handleStorage = (event: StorageEvent) => {
      if (event.key === "session") {
        syncUserFromLocalStorage();
      }
    };
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  // Check deployment version
  useEffect(() => {
    checkDeploymentVersion();
  }, []); // When user status changes, check again

  // Check user login status
  useEffect(() => {
    if (!isLoading && !user) {
      // When page is loaded, if not logged in, trigger session expired event
      // Only trigger on non-home path, and only when there is a session before
      if (pathname && pathname !== '/' && !pathname.startsWith('/?') && shouldCheckSession) {
        window.dispatchEvent(new CustomEvent(EVENTS.SESSION_EXPIRED, {
          detail: { message: t('auth.sessionExpired') }
        }));
        setShouldCheckSession(false); // After triggering the expired event, disable session check
      }
    }
  }, [user, isLoading, pathname, shouldCheckSession, t]);

  // Session validity check, ensure the session in local storage is not expired
  useEffect(() => {
    if (!user || isLoading || !shouldCheckSession) return;

    const verifySession = () => {
      const lastVerifyTime = Number(localStorage.getItem('lastSessionVerifyTime') || 0);
      const now = Date.now();
      // If the last verification is less than 10 seconds, skip
      if (now - lastVerifyTime < 10000) {
        return;
      }

      try {
        const sessionObj = getSessionFromStorage();
        if (!sessionObj || sessionObj.expires_at * 1000 <= now) {
          // Session does not exist or has expired
          window.dispatchEvent(new CustomEvent(EVENTS.SESSION_EXPIRED, {
            detail: { message: t('auth.sessionExpired') }
          }));
          setShouldCheckSession(false);
        }

        localStorage.setItem('lastSessionVerifyTime', now.toString());
      } catch (error) {
        log.error('Session validation failed:', error);
      }
    };

    // Immediately execute once
    verifySession();

    // Poll every 10 seconds
    const intervalId = setInterval(verifySession, 10000);

    return () => clearInterval(intervalId);
  }, [user, isLoading, shouldCheckSession, t]);

  const openLoginModal = () => {
    setIsRegisterModalOpen(false)
    setIsLoginModalOpen(true)
  }

  const closeLoginModal = () => {
    setIsLoginModalOpen(false)
  }

  const openRegisterModal = () => {
    setIsLoginModalOpen(false)
    setIsRegisterModalOpen(true)
  }

  const closeRegisterModal = () => {
    setIsRegisterModalOpen(false)
  }

  const login = async (email: string, password: string, showSuccessMessage: boolean = true) => {
    try {
      setIsLoading(true)
      
      // First check auth service availability
      const isAuthServiceAvailable = await authService.checkAuthServiceAvailable()
      if (!isAuthServiceAvailable) {
        const error = new Error(t('auth.authServiceUnavailable'))
        ;(error as any).code = STATUS_CODES.AUTH_SERVICE_UNAVAILABLE
        throw error
      }
      
      const { data, error } = await authService.signIn(email, password)

      if (error) {
        log.error("Login failed: ", error.message)
        throw error
      }

      if (data?.session?.user) {
        // Ensure role field is "user" or "admin"
        const safeUser: User = {
          id: data.session.user.id,
          email: data.session.user.email,
          role: data.session.user.role === USER_ROLES.ADMIN ? USER_ROLES.ADMIN : USER_ROLES.USER,
          avatar_url: data.session.user.avatar_url
        }
        setUser(safeUser)
        setShouldCheckSession(true) // After login, enable session check
        
        // Add delay to ensure local storage operation is completed
        setTimeout(() => {
          configService.loadConfigToFrontend()
          closeLoginModal()

          if (showSuccessMessage) {
            message.success(t('auth.loginSuccess'))
          }
          // Manually trigger storage event
          window.dispatchEvent(new StorageEvent("storage", { key: "session", newValue: localStorage.getItem("session") }))
          
          // If on the chat page, trigger conversation list update
          if (pathname.includes('/chat')) {
            window.dispatchEvent(new CustomEvent('conversationListUpdated'))
          }
        }, 150)
      }
    } catch (error: any) {
      log.error("Error during login process:", error.message)
      throw error
    } finally {
      setIsLoading(false)
    }
  }

  const register = async (email: string, password: string, isAdmin?: boolean, inviteCode?: string) => {
    try {
      setIsLoading(true)
      
      // First check auth service availability
      const isAuthServiceAvailable = await authService.checkAuthServiceAvailable()
      if (!isAuthServiceAvailable) {
        const error = new Error(t('auth.authServiceUnavailable'))
        ;(error as any).code = STATUS_CODES.AUTH_SERVICE_UNAVAILABLE
        throw error
      }
      
      const { data, error } = await authService.signUp(email, password, isAdmin, inviteCode)

      if (error) {
        throw error
      }

      if (data?.user) {
        // Ensure role field is "user" or "admin"
        const safeUser: User = {
          id: data.user.id,
          email: data.user.email,
          role: data.user.role === USER_ROLES.ADMIN ? USER_ROLES.ADMIN : USER_ROLES.USER,
          avatar_url: data.user.avatar_url
        }

        if (data.session) {
          // Register and login successfully
          setUser(safeUser)
          configService.loadConfigToFrontend()
          closeRegisterModal()
          const successMessage = isAdmin ? t('auth.adminRegisterSuccessAutoLogin') : t('auth.registerSuccessAutoLogin')
          message.success(successMessage)
          // Manually trigger storage event
          window.dispatchEvent(new StorageEvent("storage", { key: "session", newValue: localStorage.getItem("session") }))
        } else {
          // Register successfully but need to manually login
          closeRegisterModal()
          openLoginModal()
          const successMessage = isAdmin ? t('auth.adminRegisterSuccessManualLogin') : t('auth.registerSuccessManualLogin')
          message.success(successMessage)
        }
      }
    } catch (error: any) {
      throw error
    } finally {
      setIsLoading(false)
    }
  }

  const logout = async (options?: { silent?: boolean }) => {
    try {
      setIsLoading(true)
      await authService.signOut()
      setUser(null)
      // When logging out, disable session check
      setShouldCheckSession(false)
      // Only show message when user actively logout
      if (!options?.silent) {
        message.success(t("auth.logoutSuccess"))
      }
      // Manually trigger storage event
      window.dispatchEvent(new StorageEvent("storage", { key: "session", newValue: null }))
    } catch (error: any) {
      log.error("Logout failed:", error.message)
      message.error(t('auth.logoutFailed'))
    } finally {
      setIsLoading(false)
    }
  }

  const revoke = async () => {
    try {
      setIsLoading(true);
      await authService.revoke();
      setUser(null);
      setShouldCheckSession(false);
      message.success(t("auth.revokeSuccess"));
      // Manually trigger storage event
      window.dispatchEvent(
        new StorageEvent("storage", { key: "session", newValue: null })
      );
    } catch (error: any) {
      log.error("Revoke failed:", error?.message || error);
      message.error(t("auth.revokeFailed"));
    } finally {
      setIsLoading(false);
    }
  };

  const contextValue: AuthContextType = {
    user,
    isLoading,
    isLoginModalOpen,
    isRegisterModalOpen,
    isFromSessionExpired,
    authServiceUnavailable,
    isSpeedMode,
    isReady,
    openLoginModal,
    closeLoginModal,
    openRegisterModal,
    closeRegisterModal,
    setIsFromSessionExpired,
    login,
    register,
    logout,
    revoke,
  };

  return children(contextValue);
}

// Custom hook for accessing auth context
export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return context
}

// Export auth context for Provider use
export { AuthContext } 