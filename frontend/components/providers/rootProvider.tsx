// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, type ReactNode } from "react";
import { ConfigProvider, App } from "antd";
import antdEnUs from "antd/locale/en_US";
import antdZhCn from "antd/locale/zh_CN";
import "dayjs/locale/zh-cn";
import { useTranslation } from "react-i18next";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/queryClient";

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
import { AutoHideScrollbars } from "./AutoHideScrollbars";
import {
  BRAND_CSS,
  NEXENT_THEME,
  NEXENT_BUTTON_DEFAULTS,
  NEXENT_SELECT_DEFAULTS,
  NEXENT_BADGE_DEFAULTS,
} from "@/const/brand";

function AppReadyWrapper({ children }: { children?: ReactNode }) {
  const { isDeploymentReady, isSpeedMode } = useDeployment();
  const auth = useAuthenticationContext();
  const authz = useAuthorizationContext();
  useSessionManager(authz.user);

  // In speed mode, skip auth checks since authentication is bypassed
  // isAuthChecking: allow rendering during auth state check to avoid blocking UI
  const isAuthReady =
    isSpeedMode ||
    !auth.isLoading ||
    auth.isAuthenticated ||
    auth.isAuthChecking;
  const isAuthzReady =
    isSpeedMode ||
    !authz.isLoading ||
    auth.isAuthenticated ||
    auth.isAuthChecking;
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
  const { i18n } = useTranslation("common");
  const language = i18n.resolvedLanguage ?? i18n.language;
  const antdLocale = language?.startsWith("zh") ? antdZhCn : antdEnUs;

  useEffect(() => {
    // Legacy static portals do not inherit the normal provider tree.
    ConfigProvider.config({
      holderRender: (holder) => (
        <ConfigProvider
          locale={antdLocale}
          theme={NEXENT_THEME}
          button={NEXENT_BUTTON_DEFAULTS}
          select={NEXENT_SELECT_DEFAULTS}
          badge={NEXENT_BADGE_DEFAULTS}
        >
          {holder}
        </ConfigProvider>
      ),
    });
    return () => ConfigProvider.config({ holderRender: undefined });
  }, [antdLocale]);
  return (
    <ConfigProvider
      locale={antdLocale}
      theme={NEXENT_THEME}
      button={NEXENT_BUTTON_DEFAULTS}
      select={NEXENT_SELECT_DEFAULTS}
      badge={NEXENT_BADGE_DEFAULTS}
      getPopupContainer={() => document.body}
      modal={{ mask: { closable: false } }}
      drawer={{ mask: { closable: false } }}
    >
      <style>{BRAND_CSS}</style>
      <QueryClientProvider client={queryClient}>
        <App>
          <AutoHideScrollbars />
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
