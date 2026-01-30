"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useRouter, usePathname } from "next/navigation";
import { Menu, ConfigProvider } from "antd";
import {
  Bot,
  Globe,
  Zap,
  Settings,
  BookOpen,
  User,
  Database,
  ShoppingBag,
  Code,
  Home,
  Puzzle,
  Activity,
  Building2,
} from "lucide-react";
import type { MenuProps } from "antd";
import { useAuth } from "@/hooks/useAuth";
import { SIDER_CONFIG } from "@/const/layoutConstants";

interface SideNavigationProps {
  onAuthRequired?: () => void;
  onAdminRequired?: () => void;
  collapsed?: boolean;
}

/**
 * Side navigation component with collapsible menu
 * Displays main navigation items for the application
 */
export function SideNavigation({
  onAuthRequired,
  onAdminRequired,
  collapsed,
}: SideNavigationProps) {
  const { t } = useTranslation("common");
  const { user, isSpeedMode } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const [selectedKey, setSelectedKey] = useState("home");
  const isCollapsed = typeof collapsed === "boolean" ? collapsed : false;

  // Add path to key mapping
  const pathToKeyMap: Record<string, string> = {
    "/": "home",
    "/chat": "chat",
    "/setup": "setup",
    "/space": "space",
    "/market": "market",
    "/agents": "agents",
    "/knowledges": "knowledges",
    "/mcp-tools": "mcp-tools",
    "/monitoring": "monitoring",
    "/models": "models",
    "/memory": "memory",
  };

  // Add useEffect to listen to pathname changes and update selectedKey
  useEffect(() => {
    // Extract actual path from pathname (remove locale prefix)
    const segments = pathname.split("/").filter(Boolean);
    // If the first segment is locale (zh or en), remove it
    if (segments.length > 0 && (segments[0] === "zh" || segments[0] === "en")) {
      segments.shift();
    }
    // Rebuild path
    const currentPath = "/" + segments.join("/");

    // Find corresponding key, default to home if not found
    const matchedKey = pathToKeyMap[currentPath] || "home";
    setSelectedKey(matchedKey);
  }, [pathname]);

  // Helper function to create menu item with consistent icon styling
  const createMenuItem = (
    key: string,
    path: string,
    Icon: any,
    labelKey: string,
    requiresAuth = false,
    requiresAdmin = false
  ) => ({
    key,
    path,
    icon: <Icon className="w-4 h-4" />,
    label: t(labelKey),
    onClick: () => {
      if (!isSpeedMode && requiresAdmin && user?.role !== "admin") {
        onAdminRequired?.();
      } else if (!isSpeedMode && requiresAuth && !user) {
        onAuthRequired?.();
      } else {
        setSelectedKey(key);
        if (path) {
          router.push(path);
        }
      }
    },
  });

  // Menu items configuration - paths without locale prefix (middleware will add it)
  const menuItems: MenuProps["items"] = [
    createMenuItem("0", "/", Home, "sidebar.homePage"),
    createMenuItem("1", "/chat", Bot, "sidebar.startChat", true),
    createMenuItem("2", "/setup", Zap, "sidebar.quickConfig", false, true),
    createMenuItem("3", "/space", Globe, "sidebar.agentSpace", true),
    createMenuItem("4", "/market", ShoppingBag, "sidebar.agentMarket", true),
    createMenuItem("5", "/agents", Code, "sidebar.agentDev", false, true),
    createMenuItem("6", "/knowledges", BookOpen, "sidebar.knowledgeBase", true),
    createMenuItem(
      "10",
      "/mcp-tools",
      Puzzle,
      "sidebar.mcpToolsManagement",
      false,
      true
    ),
    createMenuItem(
      "11",
      "/monitoring",
      Activity,
      "sidebar.monitoringManagement",
      false,
      true
    ),
    createMenuItem(
      "7",
      "/models",
      Settings,
      "sidebar.modelManagement",
      false,
      true
    ),
    createMenuItem(
      "8",
      "/memory",
      Database,
      "sidebar.memoryManagement",
      false,
      true
    ),
  ];

  return (
    <ConfigProvider>
      <div className="relative">
        <div
          className="flex-shrink-0"
          style={{
            width: isCollapsed
              ? SIDER_CONFIG.COLLAPSED_WIDTH
              : SIDER_CONFIG.EXPANDED_WIDTH,
          }}
        >
          <div className="py-2 h-full">
            <Menu
              mode="inline"
              inlineCollapsed={isCollapsed}
              selectedKeys={[selectedKey]}
              items={menuItems}
              className="bg-transparent border-r-0 h-full"
            />
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
}
