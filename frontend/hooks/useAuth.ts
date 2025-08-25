"use client"

import { useState, useEffect, useContext, createContext, type ReactNode } from "react"
import { App } from "antd"
import { authService } from "@/services/authService"
import { getSessionFromStorage } from "@/lib/auth"
import { configService } from "@/services/configService"
import { User, AuthContextType } from "@/types/auth"
import { EVENTS, STATUS_CODES } from "@/types/auth"
import { usePathname } from "next/navigation"
import { useTranslation } from "react-i18next"
import { API_ENDPOINTS } from "@/services/api"

// 创建认证上下文
const AuthContext = createContext<AuthContextType | undefined>(undefined)

// 认证提供者组件
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

  // 检查认证服务可用性
  const checkAuthService = async () => {
    const isAvailable = await authService.checkAuthServiceAvailable()
    setAuthServiceUnavailable(!isAvailable)
    return isAvailable
  }

  // 当登录或注册弹窗打开时检查认证服务可用性
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
      console.error('Failed to check deployment version:', error);
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
      console.error('Auto-login failed:', error);
    }
  };

  // 初始化时检查用户会话（只从本地读取，不主动请求后端）
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
              role: session.user.role === "admin" ? "admin" : "user",
              avatar_url: session.user.avatar_url
            };
            setUser(safeUser);
            setShouldCheckSession(true); // 有用户时启用会话检查
            return;
          }
        } catch (e) {
          // ignore parse error
        }
      }
      setUser(null);
      setShouldCheckSession(false); // 无用户时禁用会话检查
    };

    setIsLoading(true);
    syncUserFromLocalStorage();
    setIsLoading(false);

    // 监听本地session变化
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

  // 检查部署版本
  useEffect(() => {
    checkDeploymentVersion();
  }, []); // 当用户状态变化时重新检查

  // 检查用户登录状态
  useEffect(() => {
    if (!isLoading && !user) {
      // 页面加载完成后，如果没有登录，则触发会话过期事件
      // 只在非首页路径触发，且仅在之前有会话的情况下触发
      if (pathname && pathname !== '/' && !pathname.startsWith('/?') && shouldCheckSession) {
        window.dispatchEvent(new CustomEvent(EVENTS.SESSION_EXPIRED, {
          detail: { message: t('auth.sessionExpired') }
        }));
        setShouldCheckSession(false); // 触发过期事件后禁用会话检查
      }
    }
  }, [user, isLoading, pathname, shouldCheckSession, t]);

  // 会话有效性检查，确保本地存储的会话不是过期的
  useEffect(() => {
    if (!user || isLoading || !shouldCheckSession) return;

    const verifySession = () => {
      const lastVerifyTime = Number(localStorage.getItem('lastSessionVerifyTime') || 0);
      const now = Date.now();
      // 如果距离上次验证不足 10 秒，跳过
      if (now - lastVerifyTime < 10000) {
        return;
      }

      try {
        const sessionObj = getSessionFromStorage();
        if (!sessionObj || sessionObj.expires_at * 1000 <= now) {
          // 会话不存在或已过期
          window.dispatchEvent(new CustomEvent(EVENTS.SESSION_EXPIRED, {
            detail: { message: t('auth.sessionExpired') }
          }));
          setShouldCheckSession(false);
        }

        localStorage.setItem('lastSessionVerifyTime', now.toString());
      } catch (error) {
        console.error('Session validation failed:', error);
      }
    };

    // 立即执行一次
    verifySession();

    // 每 10 秒轮询一次
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
      
      // 首先检查认证服务可用性
      const isAuthServiceAvailable = await authService.checkAuthServiceAvailable()
      if (!isAuthServiceAvailable) {
        const error = new Error(t('auth.authServiceUnavailable'))
        ;(error as any).code = STATUS_CODES.AUTH_SERVICE_UNAVAILABLE
        throw error
      }
      
      const { data, error } = await authService.signIn(email, password)

      if (error) {
        console.error("Login failed: ", error.message)
        throw error
      }

      if (data?.session?.user) {
        // Ensure role field is "user" or "admin"
        const safeUser: User = {
          id: data.session.user.id,
          email: data.session.user.email,
          role: data.session.user.role === "admin" ? "admin" : "user",
          avatar_url: data.session.user.avatar_url
        }
        setUser(safeUser)
        setShouldCheckSession(true) // 登录成功后启用会话检查
        
        // 添加延迟确保本地存储操作完成
        setTimeout(() => {
          configService.loadConfigToFrontend()
          closeLoginModal()

          if (showSuccessMessage) {
            message.success(t('auth.loginSuccess'))
          }
          // 主动触发 storage 事件
          window.dispatchEvent(new StorageEvent("storage", { key: "session", newValue: localStorage.getItem("session") }))
          
          // If on the chat page, trigger conversation list update
          if (pathname.includes('/chat')) {
            window.dispatchEvent(new CustomEvent('conversationListUpdated'))
          }
        }, 150)
      }
    } catch (error: any) {
      console.error("Error during login process:", error.message)
      throw error
    } finally {
      setIsLoading(false)
    }
  }

  const register = async (email: string, password: string, isAdmin?: boolean, inviteCode?: string) => {
    try {
      setIsLoading(true)
      
      // 首先检查认证服务可用性
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
          role: data.user.role === "admin" ? "admin" : "user",
          avatar_url: data.user.avatar_url
        }

        if (data.session) {
          // 注册并登录成功
          setUser(safeUser)
          configService.loadConfigToFrontend()
          closeRegisterModal()
          const successMessage = isAdmin ? t('auth.adminRegisterSuccessAutoLogin') : t('auth.registerSuccessAutoLogin')
          message.success(successMessage)
          // 主动触发 storage 事件
          window.dispatchEvent(new StorageEvent("storage", { key: "session", newValue: localStorage.getItem("session") }))
        } else {
          // 注册成功但需要手动登录
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

  const logout = async () => {
    try {
      setIsLoading(true)
      await authService.signOut()
      setUser(null)
      setShouldCheckSession(false) // 登出时禁用会话检查
      message.success(t('auth.logoutSuccess'))
      // 主动触发 storage 事件
      window.dispatchEvent(new StorageEvent("storage", { key: "session", newValue: null }))
    } catch (error: any) {
      console.error("Logout failed:", error.message)
      message.error(t('auth.logoutFailed'))
    } finally {
      setIsLoading(false)
    }
  }

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
  };

  return children(contextValue);
}

// 自定义钩子用于访问认证上下文
export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return context
}

// 导出认证上下文供Provider使用
export { AuthContext } 