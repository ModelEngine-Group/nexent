"use client";

import { ReactNode, useState } from "react";
import { usePathname } from "next/navigation";
import { Layout, Button, Spin } from "antd";
import { TopNavbar } from "@/components/navigation/TopNavbar";
import { SideNavigation } from "@/components/navigation/SideNavigation";
import { FooterLayout } from "@/components/navigation/FooterLayout";
import {
  HEADER_CONFIG,
  FOOTER_CONFIG,
  SIDER_CONFIG,
} from "@/const/layoutConstants";
import { AuthDialogs } from "@/components/auth/AuthDialogs";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { getEffectiveRoutePath } from "@/lib/auth";

const { Header, Sider, Content, Footer } = Layout;

export function ClientLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated } = useAuthenticationContext();
  const { isAuthorized } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();

  // Check if current route is setup page
  const isSetupPage = pathname?.includes("/setup");

  const isChatPage = pathname?.includes("/chat");

  // Home page does not require authorization
  const isHomePage = getEffectiveRoutePath(pathname) === "/";

  // Sidebar collapse state
  const [collapsed, setCollapsed] = useState(false);

  // Layout style calculations
  const headerReservedHeight = parseInt(HEADER_CONFIG.RESERVED_HEIGHT);
  const footerReservedHeight = parseInt(FOOTER_CONFIG.RESERVED_HEIGHT);

  const layoutStyle: React.CSSProperties = {
    height: "100vh",
    width: "100vw",
    overflow: "hidden",
    backgroundColor: "#fff",
  };

  const siderStyle: React.CSSProperties = {
    textAlign: "start",
    display: "flex",
    flexDirection: "column",
    alignItems: "stretch",
    justifyContent: "flex-start",
    position: "fixed",
    top: headerReservedHeight,
    bottom: isSetupPage ? 0 : footerReservedHeight,
    left: 0,
    backgroundColor: "#fff",
    overflow: "visible",
    zIndex: 998,
  };

  const siderInnerStyle: React.CSSProperties = {
    height: "100%",
    overflowY: "auto",
    overflowX: "hidden",
    WebkitOverflowScrolling: "touch",
    display: "flex",
    flexDirection: "column",
  };

  const headerStyle: React.CSSProperties = {
    textAlign: "center",
    height: headerReservedHeight,
    backgroundColor: "#fff",
    lineHeight: "64px",
    paddingInline: 0,
    flexShrink: 0,
  };

  const footerStyle: React.CSSProperties = {
    textAlign: "center",
    height: footerReservedHeight,
    lineHeight: footerReservedHeight,
    padding: 0,
    flexShrink: 0,
    backgroundColor: "#fff",
  };

  const contentStyle: React.CSSProperties = {
    height: "100%",
    overflowY: "auto",
    overflowX: "hidden",
    position: "relative",
    marginLeft: collapsed
      ? `${SIDER_CONFIG.COLLAPSED_WIDTH}px`
      : `${SIDER_CONFIG.EXPANDED_WIDTH}px`,
    backgroundColor: "#fff",
  };

  return (
    <Layout style={layoutStyle}>
      <Header style={headerStyle}>
        <TopNavbar isChatPage={isChatPage}/>
      </Header>

      <Layout>
        <Sider
          style={siderStyle}
          width={SIDER_CONFIG.EXPANDED_WIDTH}
          collapsed={collapsed}
          trigger={null}
          breakpoint="lg"
          collapsedWidth={SIDER_CONFIG.COLLAPSED_WIDTH}
          className="dark:bg-slate-900/95 border-r border-slate-200 dark:border-slate-700 backdrop-blur-sm shadow-sm"
        >
          <div style={siderInnerStyle}>
            <SideNavigation collapsed={collapsed} />
          </div>
          <Button
            type="primary"
            shape="circle"
            size="small"
            onClick={() => setCollapsed(!collapsed)}
            style={{
              position: "absolute",
              top: "50%",
              transform: "translateY(-50%)",
              right: "-12px",
              transition: "right 0.2s ease, left 0.2s ease",
              zIndex: 999,
            }}
            icon={
              collapsed ? (
                <ChevronRight className="w-3 h-3" />
              ) : (
                <ChevronLeft className="w-3 h-3" />
              )
            }
          />
        </Sider>

        {/* Don't render children until authorization is complete (except home page) */}
        <Content style={contentStyle}>
          {isHomePage || isAuthorized ? (
            children
          ) : (
            <div className="flex items-center justify-center h-full w-full">
              <Spin/>
            </div>
          )}
        </Content>
      </Layout>

      {/* Conditionally render footer */}
      {!isSetupPage && (
        <Footer style={footerStyle}>
          <FooterLayout />
        </Footer>
      )}

      {/* Global authentication dialogs */}
      {!isSpeedMode && (
        <>
          <AuthDialogs />
        </>
      )}
    </Layout>
  );
}
