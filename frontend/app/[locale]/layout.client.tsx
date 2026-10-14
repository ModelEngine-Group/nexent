// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { type CSSProperties, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Layout, Spin } from "antd";
import { SideNavigation } from "@/components/navigation/SideNavigation";
import { SIDER_CONFIG } from "@/const/layoutConstants";
import { AuthDialogs } from "@/components/auth/AuthDialogs";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { getEffectiveRoutePath } from "@/lib/auth";
import { QuotaWarningMonitor } from "@/components/quota/QuotaWarningMonitor";
import { MemoryEmbeddingMonitor } from "@/components/memory/MemoryEmbeddingMonitor";

const { Sider, Content } = Layout;

export function ClientLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { isAuthorized } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();

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
    width: SIDER_CONFIG.WIDTH,
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
        width={SIDER_CONFIG.WIDTH}
        collapsedWidth={SIDER_CONFIG.WIDTH}
        trigger={null}
        className="!bg-[#f0f0f0] border-r border-[#c9c9c9]"
      >
        <SideNavigation />
      </Sider>

      <Layout
        style={{
          minHeight: "100vh",
          marginLeft: `${SIDER_CONFIG.WIDTH}px`,
        }}
      >
        <Content style={contentStyle}>
          {isHomePage || isOAuthCompletePage || isSharePage || isAuthorized ? (
            children
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <Spin />
            </div>
          )}
        </Content>
      </Layout>

      {!isSpeedMode && <AuthDialogs />}
    </Layout>
  );
}
