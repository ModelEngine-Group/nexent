"use client";

import { ReactNode } from "react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  AuthProvider,
  AuthContext,
  useAuth,
} from "@/hooks/useAuth";

import { LoginModal, RegisterModal, SessionListeners } from "@/components/auth";
import { FullScreenLoading } from "@/components/ui/loading";
import { useDeployment } from "./deploymentProvider";

function AppReadyWrapper({ children }: { children: ReactNode }) {
  const { isDeploymentReady } = useDeployment();
  const auth = useAuth();
  const isAuthReady = (auth as any).isAuthReady;

  const isAppReady = isDeploymentReady && isAuthReady;

  return isAppReady ? <>{children}</> : <FullScreenLoading />;
}

/**
 * RootProvider Component
 * Integrates all necessary providers for the application
 */
export function RootProvider({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider getPopupContainer={() => document.body}>
      <QueryClientProvider client={queryClient}>
        <App>
          <AuthProvider>
            {(authContextValue) => (
              <AuthContext.Provider value={authContextValue}>
                <AppReadyWrapper>
                  <>
                    {children}
                    <SessionListeners />
                  </>
                </AppReadyWrapper>
                <LoginModal />
                <RegisterModal />
              </AuthContext.Provider>
            )}
          </AuthProvider>
        </App>
      </QueryClientProvider>
    </ConfigProvider>
  );
}

// Create a single QueryClient instance for the application
const queryClient = new QueryClient();
