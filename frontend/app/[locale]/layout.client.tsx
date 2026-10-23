// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useCallback,
  useRef,
  useState,
  useTransition,
  type CSSProperties,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { Layout, Spin } from "antd";
import { SideNavigation } from "@/components/navigation/SideNavigation";
import { SIDER_CONFIG } from "@/const/layoutConstants";
import { AuthDialogs } from "@/components/auth/AuthDialogs";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { getEffectiveRoutePath } from "@/lib/auth";
import { QuotaWarningMonitor } from "@/components/quota/QuotaWarningMonitor";
import { MemoryEmbeddingMonitor } from "@/components/memory/MemoryEmbeddingMonitor";
import { RouteTransitionContent } from "@/components/navigation/RouteTransitionContent";

const { Sider, Content } = Layout;

export function ClientLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const contentRef = useRef<HTMLDivElement>(null);
  const [isNavigating, startNavigation] = useTransition();
  const [targetPath, setTargetPath] = useState<string | null>(null);
  const navigate = useCallback(
    (path: string) => {
      if (contentRef.current) contentRef.current.scrollTop = 0;
      setTargetPath(path);
      startNavigation(() => router.push(path));
    },
    [router]
  );
  const { isAuthorized } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const [sidebarPinned, setSidebarPinned] = useState(false);
  const sidebarWidth = sidebarPinned ? 240 : SIDER_CONFIG.WIDTH;

  const effectivePath = getEffectiveRoutePath(pathname);
  const isHomePage = effectivePath === "/";
  const isOAuthCompletePage = effectivePath === "/oauth/complete";
  const isSharePage = effectivePath.startsWith("/share/");

  const layoutStyle: CSSProperties = {
    height: "100vh",
    width: "100vw",
    overflow: "hidden",
    backgroundColor: "#fff",
  };

  const siderStyle: CSSProperties = {
    textAlign: "start",
    display: "flex",
    flexDirection: "column",
    alignItems: "stretch",
    justifyContent: "flex-start",
    position: "fixed",
    top: 0,
    bottom: 0,
    left: 0,
    width: sidebarWidth,
    backgroundColor: "#f0f0f0",
    overflow: "visible",
    zIndex: 30,
  };

  const contentStyle: CSSProperties = {
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
    overflowX: "hidden",
    position: "relative",
    backgroundColor: "#fff",
  };

  if (isSharePage) {
    return (
      <Layout style={layoutStyle}>
        <Content
          style={{
            height: "100%",
            overflow: "hidden",
            backgroundColor: "#fff",
          }}
        >
          {children}
        </Content>
        {!isSpeedMode && <AuthDialogs />}
      </Layout>
    );
  }

  return (
    <Layout style={layoutStyle}>
      <QuotaWarningMonitor />
      <MemoryEmbeddingMonitor />

      <Sider
        style={siderStyle}
        width={sidebarWidth}
        collapsedWidth={SIDER_CONFIG.WIDTH}
        trigger={null}
        className="!bg-[#f0f0f0]"
      >
        <SideNavigation
          onPinnedChange={setSidebarPinned}
          onNavigate={navigate}
          isNavigating={isNavigating}
        />
      </Sider>

      <Layout
        className="transition-[margin-left] duration-[180ms] motion-reduce:transition-none"
        style={{
          minHeight: "100vh",
          marginLeft: `${sidebarWidth}px`,
        }}
      >
        <Content ref={contentRef} style={contentStyle}>
          <RouteTransitionContent
            pendingPath={isNavigating ? targetPath : null}
          >
            {isHomePage ||
            isOAuthCompletePage ||
            isSharePage ||
            isAuthorized ? (
              children
            ) : (
              <div className="flex h-full w-full items-center justify-center">
                <Spin />
              </div>
            )}
          </RouteTransitionContent>
        </Content>
      </Layout>

      {!isSpeedMode && <AuthDialogs />}
    </Layout>
  );
}
