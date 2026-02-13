"use client";

import { ReactNode } from "react";
import { ConfigProvider, App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  AuthenticationProvider,
  useAuthenticationContext,
} from "@/components/providers/AuthenticationProvider";
import {
  AuthorizationProvider,
  useAuthorizationContext,
} from "@/components/providers/AuthorizationProvider";

import { LoginModal } from "@/components/auth/loginModal";
import { RegisterModal } from "@/components/auth/registerModal";
import { FullScreenLoading } from "@/components/ui/loading";
import { useDeployment } from "./deploymentProvider";
import { useSessionManager } from "@/hooks/auth/useSessionManager";

function AppReadyWrapper({ children }: { children?: ReactNode }) {
  useSessionManager();

  const { isDeploymentReady, isSpeedMode } = useDeployment();
  const auth = useAuthenticationContext();
  const authz = useAuthorizationContext();

  // In speed mode, skip auth checks since authentication is bypassed
  // isAuthChecking: allow rendering during auth state check to avoid blocking UI
  const isAuthReady = isSpeedMode || !auth.isLoading || auth.isAuthenticated || auth.isAuthChecking;
  const isAuthzReady = isSpeedMode || !authz.isLoading || auth.isAuthenticated || auth.isAuthChecking;
  const isAppReady = isDeploymentReady && isAuthReady && isAuthzReady;

  // If login or register modal is open, user is performing an operation,
  // don't show full screen loading (they can already see the page)
  const isUserOperating = auth.isLoginModalOpen || auth.isRegisterModalOpen;
  
  // Only show FullScreenLoading during initial load, not during user operations
  if (isAppReady || isUserOperating) {
    return <>{children}</>;
  }
  
  return <FullScreenLoading />;
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
            <AuthenticationProvider>
              <AuthorizationProvider>
                <AppReadyWrapper>
                  <>{children}</>
                </AppReadyWrapper>
                <LoginModal />
                <RegisterModal />
              </AuthorizationProvider>
            </AuthenticationProvider>
        </App>
      </QueryClientProvider>
    </ConfigProvider>
  );
}

// Create a single QueryClient instance for the application
const queryClient = new QueryClient();
