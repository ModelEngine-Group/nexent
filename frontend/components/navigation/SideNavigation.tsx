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
import { HEADER_CONFIG, FOOTER_CONFIG, SIDER_CONFIG } from "@/const/layoutConstants";

const { Sider } = Layout;

interface SideNavigationProps {
  onAuthRequired?: () => void;
  onAdminRequired?: () => void;
  onViewChange?: (view: string) => void;
  currentView?: string;
  collapsed?: boolean;
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
  collapsed: collapsedProp,
}: SideNavigationProps) {
  const { t } = useTranslation("common");
  const { user, isSpeedMode } = useAuth();
  const pathname = usePathname();
  // Support controlled collapse from parent; fall back to internal state if needed
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const [selectedKey, setSelectedKey] = useState("0");
  const isCollapsed = typeof collapsedProp === "boolean" ? collapsedProp : internalCollapsed;
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

  // Helper function to create menu item with consistent icon styling
  const createMenuItem = (key: string, Icon: any, labelKey: string, view: string, requiresAuth = false, requiresAdmin = false) => ({
    key,
    icon: <Icon className="w-4 h-4" />,
    label: t(labelKey),
    onClick: () => {
      if (!isSpeedMode && requiresAdmin && user?.role !== "admin") {
        onAdminRequired?.();
      } else if (!isSpeedMode && requiresAuth && !user) {
        onAuthRequired?.();
      } else {
        onViewChange?.(view);
      }
    },
  });

  // Menu items configuration
  const menuItems: MenuProps["items"] = [
    createMenuItem("0", Home, "sidebar.homePage", "home"),
    createMenuItem("1", Bot, "sidebar.startChat", "chat", true),
    createMenuItem("2", Zap, "sidebar.quickConfig", "setup", false, true),
    createMenuItem("3", Globe, "sidebar.agentSpace", "space", true),
    createMenuItem("4", ShoppingBag, "sidebar.agentMarket", "market", true),
    createMenuItem("5", Code, "sidebar.agentDev", "agents", false, true),
    createMenuItem("6", BookOpen, "sidebar.knowledgeBase", "knowledges", true),
    createMenuItem("10", Puzzle, "sidebar.mcpToolsManagement", "mcpTools", false, true),
    createMenuItem("11", Activity, "sidebar.monitoringManagement", "monitoring", false, true),
    createMenuItem("7", Settings, "sidebar.modelManagement", "models", false, true),
    createMenuItem("8", Database, "sidebar.memoryManagement", "memory", false, true),
    createMenuItem("9", Users, "sidebar.userManagement", "users", false, true),
  ];

  // Calculate sidebar height and position dynamically
  const sidebarHeight = `calc(100vh - ${HEADER_CONFIG.RESERVED_HEIGHT} - ${FOOTER_CONFIG.RESERVED_HEIGHT})`;
  const sidebarTop = HEADER_CONFIG.RESERVED_HEIGHT;

  return (
    <ConfigProvider>
      <div className="relative">
        <div
          className="flex-shrink-0"
          style={{
            width: isCollapsed ? SIDER_CONFIG.COLLAPSED_WIDTH : SIDER_CONFIG.EXPANDED_WIDTH,
          }}
        >
            <div className="py-2 h-full">
              <Menu
                mode="inline"
                inlineCollapsed={isCollapsed}
                selectedKeys={[selectedKey]}
                items={menuItems}
                onClick={({ key }) => setSelectedKey(key)}
                className="bg-transparent border-r-0 h-full"
              />
            </div>
        </div>
      </div>
    </ConfigProvider>
  );
}

