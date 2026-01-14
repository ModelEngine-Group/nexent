"use client";

import { ReactNode, useState } from "react";
import { Layout, Button } from "antd";
import { TopNavbar } from "@/components/navigation/TopNavbar";
import { SideNavigation } from "@/components/navigation/SideNavigation";
import { FooterLayout } from "@/components/navigation/FooterLayout";
import {
  HEADER_CONFIG,
  FOOTER_CONFIG,
  SIDER_CONFIG,
} from "@/const/layoutConstants";
import { AuthDialogs } from "@/components/homepage/AuthDialogs";
import { useAuth } from "@/hooks/useAuth";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { usePathname } from "next/navigation";

const { Header, Sider, Content, Footer } = Layout;

export function ClientLayout({ children }: { children: ReactNode }) {
  const { user, openLoginModal, openRegisterModal, isSpeedMode } = useAuth();
  const pathname = usePathname();

  // Check if current route is setup page
  const isSetupPage = pathname?.includes("/setup");

  // Authentication dialog states
  const [loginPromptOpen, setLoginPromptOpen] = useState(false);
  const [adminRequiredPromptOpen, setAdminRequiredPromptOpen] = useState(false);

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
    overflowY: "auto",
    overflowX: "hidden",
    position: "relative",
    marginLeft: collapsed
      ? `${SIDER_CONFIG.COLLAPSED_WIDTH}px`
      : `${SIDER_CONFIG.EXPANDED_WIDTH}px`,
    backgroundColor: "#fff",
  };

  // Authentication handlers
  const handleAuthRequired = () => {
    if (!isSpeedMode && !user) {
      setLoginPromptOpen(true);
    }
  };

  const handleAdminRequired = () => {
    if (!isSpeedMode && user?.role !== "admin") {
      setAdminRequiredPromptOpen(true);
    }
  };

  const handleCloseLoginPrompt = () => setLoginPromptOpen(false);
  const handleCloseAdminPrompt = () => setAdminRequiredPromptOpen(false);

  return (
    <Layout style={layoutStyle}>
      <Header style={headerStyle}>
        <TopNavbar />
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
            <SideNavigation
              onAuthRequired={handleAuthRequired}
              onAdminRequired={handleAdminRequired}
              collapsed={collapsed}
            />
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

        <Content style={contentStyle}>{children}</Content>
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
          <AuthDialogs
            loginPromptOpen={loginPromptOpen}
            adminPromptOpen={adminRequiredPromptOpen}
            onCloseLoginPrompt={handleCloseLoginPrompt}
            onCloseAdminPrompt={handleCloseAdminPrompt}
            onLoginClick={() => {
              setLoginPromptOpen(false);
              setAdminRequiredPromptOpen(false);
              openLoginModal();
            }}
            onRegisterClick={() => {
              setLoginPromptOpen(false);
              setAdminRequiredPromptOpen(false);
              openRegisterModal();
            }}
          />
        </>
      )}
    </Layout>
  );
}
