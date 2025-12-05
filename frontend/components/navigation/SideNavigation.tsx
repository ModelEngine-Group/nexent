"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { usePathname } from "next/navigation";
import { Layout, Menu, ConfigProvider, Button } from "antd";
import {
  Bot,
  Globe,
  Zap,
  Settings,
  BookOpen,
  Users,
  Database,
  ShoppingBag,
  Code,
  ChevronLeft,
  ChevronRight,
  Home,
  Puzzle,
  Activity,
} from "lucide-react";
import type { MenuProps } from "antd";
import { useAuth } from "@/hooks/useAuth";
import { HEADER_CONFIG, FOOTER_CONFIG } from "@/const/layoutConstants";

const { Sider } = Layout;

interface SideNavigationProps {
  onAuthRequired?: () => void;
  onAdminRequired?: () => void;
  onViewChange?: (view: string) => void;
  currentView?: string;
}

/**
 * Get menu key based on current pathname
 */
function getMenuKeyFromPathname(pathname: string): string {
  // Remove locale prefix (e.g., /zh/, /en/)
  const segments = pathname.split('/').filter(Boolean);
  const pathWithoutLocale = segments.length > 1 ? segments[1] : '';
  
  // Map paths to menu keys
  const pathToKeyMap: Record<string, string> = {
    '': '0',           // Home page
    'chat': '1',       // Start chat (separate page)
    'setup': '2',      // Quick config
    'space': '3',      // Agent space
    'market': '4',     // Agent market
    'agents': '5',     // Agent dev
    'knowledges': '6', // Knowledge base
    'models': '7',     // Model management
    'memory': '8',     // Memory management
    'users': '9',       // User management
    'mcp-tools': '10',  // MCP tools management
    'monitoring': '11', // Monitoring and operations
  };
  
  return pathToKeyMap[pathWithoutLocale] || '0';
}

/**
 * Side navigation component with collapsible menu
 * Displays main navigation items for the application
 */
export function SideNavigation({
  onAuthRequired,
  onAdminRequired,
  onViewChange,
  currentView,
}: SideNavigationProps) {
  const { t } = useTranslation("common");
  const { user, isSpeedMode } = useAuth();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [selectedKey, setSelectedKey] = useState("0");
  const expandedWidth = 277;
  const collapsedWidth = 64;
  const siderWidth = collapsed ? collapsedWidth : expandedWidth;
  
  // Update selected key when pathname or currentView changes
  useEffect(() => {
    // If we have a currentView from parent, use it to determine the key
    if (currentView) {
      const viewToKeyMap: Record<string, string> = {
        home: "0",
        chat: "1",
        setup: "2",
        space: "3",
        market: "4",
        agents: "5",
        knowledges: "6",
        models: "7",
        memory: "8",
        users: "9",
        mcpTools: "10",
        monitoring: "11",
      };
      setSelectedKey(viewToKeyMap[currentView] || '0');
    } else {
      // Otherwise, fall back to pathname-based selection
      const key = getMenuKeyFromPathname(pathname);
      setSelectedKey(key);
    }
  }, [pathname, currentView]);

  // Menu items configuration
  const menuItems: MenuProps["items"] = [
    {
      key: "0",
      icon: <Home className="h-4 w-4" />,
      label: t("sidebar.homePage"),
      onClick: () => {
        onViewChange?.("home");
      },
    },
    {
      key: "1",
      icon: <Bot className="h-4 w-4" />,
      label: t("sidebar.startChat"),
      onClick: () => {
        if (!isSpeedMode && !user) {
          onAuthRequired?.();
        } else {
          onViewChange?.("chat");
        }
      },
    },
    {
      key: "2",
      icon: <Zap className="h-4 w-4" />,
      label: t("sidebar.quickConfig"),
      onClick: () => {
        if (!isSpeedMode && user?.role !== "admin") {
          onAdminRequired?.();
        } else {
          onViewChange?.("setup");
        }
      },
    },
    {
      key: "3",
      icon: <Globe className="h-4 w-4" />,
      label: t("sidebar.agentSpace"),
      onClick: () => {
        if (!isSpeedMode && !user) {
          onAuthRequired?.();
        } else {
          onViewChange?.("space");
        }
      },
    },
    {
      key: "4",
      icon: <ShoppingBag className="h-4 w-4" />,
      label: t("sidebar.agentMarket"),
      onClick: () => {
        if (!isSpeedMode && !user) {
          onAuthRequired?.();
        } else {
          onViewChange?.("market");
        }
      },
    },
    {
      key: "5",
      icon: <Code className="h-4 w-4" />,
      label: t("sidebar.agentDev"),
      onClick: () => {
        if (!isSpeedMode && user?.role !== "admin") {
          onAdminRequired?.();
        } else {
          onViewChange?.("agents");
        }
      },
    },
    {
      key: "6",
      icon: <BookOpen className="h-4 w-4" />,
      label: t("sidebar.knowledgeBase"),
      onClick: () => {
        if (!isSpeedMode && !user) {
          onAuthRequired?.();
        } else {
          onViewChange?.("knowledges");
        }
      },
    },
    {
      key: "10",
      icon: <Puzzle className="h-4 w-4" />,
      label: t("sidebar.mcpToolsManagement"),
      onClick: () => {
        if (!isSpeedMode && user?.role !== "admin") {
          onAdminRequired?.();
        } else {
          onViewChange?.("mcpTools");
        }
      },
    },
    {
      key: "11",
      icon: <Activity className="h-4 w-4" />,
      label: t("sidebar.monitoringManagement"),
      onClick: () => {
        if (!isSpeedMode && user?.role !== "admin") {
          onAdminRequired?.();
        } else {
          onViewChange?.("monitoring");
        }
      },
    },
    {
      key: "7",
      icon: <Settings className="h-4 w-4" />,
      label: t("sidebar.modelManagement"),
      onClick: () => {
        if (!isSpeedMode && user?.role !== "admin") {
          onAdminRequired?.();
        } else {
          onViewChange?.("models");
        }
      },
    },
    {
      key: "8",
      icon: <Database className="h-4 w-4" />,
      label: t("sidebar.memoryManagement"),
      onClick: () => {
        if (!isSpeedMode && user?.role !== "admin") {
          onAdminRequired?.();
        } else {
          onViewChange?.("memory");
        }
      },
    },
    {
      key: "9",
      icon: <Users className="h-4 w-4" />,
      label: t("sidebar.userManagement"),
      onClick: () => {
        if (!isSpeedMode && user?.role !== "admin") {
          onAdminRequired?.();
        } else {
          onViewChange?.("users");
        }
      },
    },
  ];

  // Calculate sidebar height dynamically based on header and footer reserved heights
  const headerReservedHeight = parseInt(HEADER_CONFIG.RESERVED_HEIGHT);
  const footerReservedHeight = parseInt(FOOTER_CONFIG.RESERVED_HEIGHT);
  const sidebarHeight = `calc(100vh - ${headerReservedHeight}px - ${footerReservedHeight}px)`;
  const sidebarTop = `${headerReservedHeight}px`;

  return (
    <ConfigProvider
      theme={{
        components: {
          Layout: {
            siderBg: "rgba(255, 255, 255, 0.95)",
          },
          Menu: {
            itemBg: "transparent",
            itemSelectedBg: "#e6f4ff",
            itemSelectedColor: "#1677ff",
            itemHoverBg: "#f5f5f5",
            itemHoverColor: "#1677ff",
            itemActiveBg: "#e6f4ff",
            itemColor: "#334155",
            iconSize: 16,
            itemBorderRadius: 6,
            itemMarginInline: 6,
            itemPaddingInline: 12,
            itemHeight: 36,
          },
        },
      }}
    >
      <div style={{ position: "relative" }}>
        <div style={{ width: `${siderWidth}px`, flexShrink: 0 }}>
          <Sider
            collapsed={collapsed}
            trigger={null}
            breakpoint="lg"
            collapsedWidth={collapsedWidth}
            width={expandedWidth}
            className="!bg-white/95 dark:!bg-slate-900/95 border-r border-slate-200 dark:border-slate-700 backdrop-blur-sm shadow-sm"
            style={{
              overflow: "auto",
              minHeight: sidebarHeight,
              height: sidebarHeight,
              position: "fixed",
              top: sidebarTop,
              left: 0,
              width: `${siderWidth}px`,
            }}
          >
            <div className="py-2 h-full">
              <Menu
                mode="inline"
                selectedKeys={[selectedKey]}
                items={menuItems}
                onClick={({ key }) => setSelectedKey(key)}
                className="!bg-transparent !border-r-0"
                style={{
                  height: "100%",
                  borderRight: 0,
                }}
              />
            </div>
          </Sider>
        </div>

        {/* Custom circular floating toggle button - positioned outside Sider */}
        <Button
          type="primary"
          shape="circle"
          size="small"
          onClick={() => setCollapsed(!collapsed)}
          className="shadow-md hover:shadow-lg transition-all"
          style={{
            position: "fixed",
            left: collapsed ? "52px" : "264px",
            top: "50vh",
            transform: "translateY(-50%)",
            width: "24px",
            height: "24px",
            minWidth: "24px",
            padding: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: "2px solid white",
            zIndex: 800,
            transition: "left 0.2s ease",
          }}
          icon={
            collapsed ? (
              <ChevronRight className="h-3 w-3" />
            ) : (
              <ChevronLeft className="h-3 w-3" />
            )
          }
        />
      </div>
    </ConfigProvider>
  );
}

