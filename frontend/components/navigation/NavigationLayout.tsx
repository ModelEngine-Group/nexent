"use client";

import { Layout, Button } from "antd";
import { TopNavbar } from "./TopNavbar";
import { SideNavigation } from "./SideNavigation";
import { FooterLayout } from "./FooterLayout";
import { HEADER_CONFIG, FOOTER_CONFIG, SIDER_CONFIG } from "@/const/layoutConstants";
import React from "react";
import { useState, useEffect } from "react";

import {
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

const { Header, Sider, Content, Footer } = Layout;
interface NavigationLayoutProps {
  children: React.ReactNode;
  onAuthRequired?: () => void;
  onAdminRequired?: () => void;
  showFooter?: boolean;
  contentMode?: "centered" | "scrollable" | "fullscreen";
  /** Additional title text to display after logo in top navbar */
  topNavbarAdditionalTitle?: React.ReactNode;
  /** Additional content to insert before default right nav items in top navbar */
  topNavbarAdditionalRightContent?: React.ReactNode;
  /** Callback for view changes in side navigation */
  onViewChange?: (view: string) => void;
  /** Current active view */
  currentView?: string;
}

/**
 * Main navigation layout component
 * Combines top navbar, side navigation, and optional footer with main content area
 * 
 * @param contentMode - "centered": content is centered vertically and horizontally (default)
 *                      "scrollable": content can scroll and fills the entire area
 *                      "fullscreen": content fills entire area with no padding, seamless integration
 * @param topNavbarAdditionalTitle - Additional title text after logo in top navbar
 * @param topNavbarAdditionalRightContent - Additional content before default right nav items
 */
export function NavigationLayout({
  children,
  onAuthRequired,
  onAdminRequired,
  showFooter = true,
  contentMode = "centered",
  topNavbarAdditionalTitle,
  topNavbarAdditionalRightContent,
  onViewChange,
  currentView,
}: NavigationLayoutProps) {
  // Use RESERVED_HEIGHT for layout calculations (actual space occupied)
  const headerReservedHeight = parseInt(HEADER_CONFIG.RESERVED_HEIGHT);
  const footerReservedHeight = parseInt(FOOTER_CONFIG.RESERVED_HEIGHT);
  const contentMinHeight = showFooter
    ? `calc(100vh - ${headerReservedHeight}px - ${footerReservedHeight}px)`
    : `calc(100vh - ${headerReservedHeight}px)`;
  
  const [collapsed, setCollapsed] = useState(false);

  const layoutStyle: React.CSSProperties = {
    height: "100vh", // Key: fill the viewport height
    width: "100vw", // Key: fill the viewport width
    overflow: "hidden", // Key: prevent the outermost scrollbar
    backgroundColor: "#fff"
  };

  const siderStyle: React.CSSProperties = {
    textAlign: "start",
    display: "flex", // use column layout to allow inner scrollable area
    flexDirection: "column",
    alignItems: "stretch",
    justifyContent: "flex-start",
    position: "fixed",
    top: headerReservedHeight,
    bottom: showFooter? footerReservedHeight: 0,
    left: 0,
    backgroundColor: "#fff",
    overflow: "visible",
    // Ensure the sider (and its toggle) sits above main content
    zIndex: 2000,
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
    height: headerReservedHeight, // Fixed height 64px
    backgroundColor: "#fff",
    lineHeight: "64px",
    paddingInline: 0,
    flexShrink: 0, // Prevent shrinking
  };

  const footerStyle: React.CSSProperties = {
    textAlign: "center",
    height: showFooter? footerReservedHeight: 0, // Fixed height 64px
    lineHeight: showFooter? footerReservedHeight: 0,
    padding: 0,
    flexShrink: 0, // 防止被挤压
    backgroundColor: "#fff",
  };

  const contentStyle: React.CSSProperties = {
    // Key settings:
    overflowY: "auto", // If content overflows vertically, scroll inside Content only
    overflowX: "hidden", // Hide horizontal scrollbar (optional)
    display: "flex", // (optional) used to center content for demo
    alignItems: "center", // (optional)
    justifyContent: "center", // (optional)
    position: "relative", // Allow absolute-positioned children
    marginLeft: collapsed
    ? `${SIDER_CONFIG.COLLAPSED_WIDTH}px`
    : `${SIDER_CONFIG.EXPANDED_WIDTH}px`,
    backgroundColor: "#fff"
  };

  return (
      <Layout style={layoutStyle}>
        <Header style={headerStyle}>      
          <TopNavbar 
            additionalTitle={topNavbarAdditionalTitle}
            additionalRightContent={topNavbarAdditionalRightContent}
          />
        </Header>

        <Layout >
          <Sider
            style={siderStyle}
            width={SIDER_CONFIG.EXPANDED_WIDTH}
            collapsed={collapsed}
            trigger={null}
            breakpoint="lg"
            collapsedWidth={SIDER_CONFIG.COLLAPSED_WIDTH}
            className="dark:bg-slate-900/95 border-r border-slate-200 dark:border-slate-700 backdrop-blur-sm shadow-sm"
          >
            {/* Side navigation - wrapped to allow internal vertical scrolling when needed */}
            <div style={siderInnerStyle}>
              <SideNavigation
                onAuthRequired={onAuthRequired}
                onAdminRequired={onAdminRequired}
                onViewChange={onViewChange}
                currentView={currentView}
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
                // Place toggle above most content; Sider already has high z-index
                zIndex: 3000,
              }}
              icon={collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
            />
          </Sider>
          {/* Main content area */}
          <Content style={contentStyle}
          >
            {contentMode === "centered" ? (
              <div className="w-full h-full flex items-center justify-center">
                {children}
              </div>
            ) : (
              children
            )}
          </Content>
        </Layout>

        { showFooter && 
            <Footer style={footerStyle}>
              <FooterLayout />
            </Footer> 
        }
      </Layout>
  );
}

