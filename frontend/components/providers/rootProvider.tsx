"use client"

import { ReactNode } from "react"
import { AuthProvider as AuthContextProvider, AuthContext, useAuth } from "@/hooks/useAuth"
import { ConfigProvider } from "antd"
import { LoginModal, RegisterModal, SessionListeners } from "@/components/auth"
import { FullScreenLoading } from "@/components/ui/loading"

function AppReadyWrapper({ children }: { children: ReactNode }) {
  const { isReady } = useAuth()
  return isReady ? <>{children}</> : <FullScreenLoading />
}

/**
 * 应用根Provider
 * 整合所有需要的Provider
 */
export function RootProvider({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider getPopupContainer={() => document.body}>
      <AuthContextProvider>
        {(authContextValue) => (
          <AuthContext.Provider value={authContextValue}>
            <AppReadyWrapper>
              {children}
            </AppReadyWrapper>
            <LoginModal />
            <RegisterModal />
            <SessionListeners />
          </AuthContext.Provider>
        )}
      </AuthContextProvider>
    </ConfigProvider>
  )
} 