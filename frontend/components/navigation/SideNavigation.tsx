"use client";

import { useState, useEffect, useMemo } from "react";
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
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { SIDER_CONFIG } from "@/const/layoutConstants";
import { AUTH_EVENTS } from "@/const/auth";
import { getEffectiveRoutePath } from "@/lib/auth";
import { authEvents } from "@/lib/authEvents";

interface SideNavigationProps {
  collapsed?: boolean;
}

/**
 * Route configuration interface for menu items
 */
interface RouteConfig {
  path: string;
  Icon: React.ComponentType<{ className?: string }>;
  labelKey: string;
  order: number;
}

/**
 * Static route configuration mapping
 * All available routes with their metadata
 */
const ROUTE_CONFIG: RouteConfig[] = [
  { path: "/", Icon: Home, labelKey: "sidebar.homePage", order: 0 },
  { path: "/chat", Icon: Bot, labelKey: "sidebar.startChat", order: 1 },
  { path: "/setup", Icon: Zap, labelKey: "sidebar.quickConfig", order: 2 },
  { path: "/space", Icon: Globe, labelKey: "sidebar.agentSpace", order: 3 },
  { path: "/market", Icon: ShoppingBag, labelKey: "sidebar.agentMarket", order: 4 },
  { path: "/agents", Icon: Code, labelKey: "sidebar.agentDev", order: 5 },
  { path: "/knowledges", Icon: BookOpen, labelKey: "sidebar.knowledgeBase", order: 6 },
  { path: "/mcp-tools", Icon: Puzzle, labelKey: "sidebar.mcpToolsManagement", order: 7 },
  { path: "/monitoring", Icon: Activity, labelKey: "sidebar.monitoringManagement", order: 8 },
  { path: "/models", Icon: Settings, labelKey: "sidebar.modelManagement", order: 9 },
  { path: "/memory", Icon: Database, labelKey: "sidebar.memoryManagement", order: 10 },
  { path: "/users", Icon: User, labelKey: "sidebar.userManagement", order: 11 },
  { path: "/tenant-resources", Icon: Building2, labelKey: "sidebar.tenantResources", order: 12 },
];

/**
 * Extract all available route paths from ROUTE_CONFIG
 */
const ROUTE_PATHS = ROUTE_CONFIG.map((route) => route.path);

/**
 * Side navigation component with collapsible menu
 * Displays main navigation items for the application based on user's accessible routes
 */
export function SideNavigation({
  collapsed,
}: SideNavigationProps) {
  const { t } = useTranslation("common");
  const { accessibleRoutes } = useAuthorizationContext();
  const { isAuthenticated, openAuthPromptModal } = useAuthenticationContext();
  const { isSpeedMode } = useDeployment();
  const router = useRouter();
  const pathname = usePathname();

  const [selectedKey, setSelectedKey] = useState("/");
  const [pendingNavigationPath, setPendingNavigationPath] = useState<string | null>(null);
  const isCollapsed = typeof collapsed === "boolean" ? collapsed : false;

  // Update selected key when pathname changes
  useEffect(() => {
    const currentPath = getEffectiveRoutePath(pathname);
    const matchedKey = ROUTE_PATHS.includes(currentPath) ? currentPath : "/";
    setSelectedKey(matchedKey);
  }, [pathname]);

  // Listen for login success event and navigate to pending path
  useEffect(() => {
    const handleLoginSuccess = () => {
      if (pendingNavigationPath && isAuthenticated) {
        // Small delay to ensure authentication state is fully updated
        setTimeout(() => {
          router.push(pendingNavigationPath);
          setPendingNavigationPath(null);
        }, 200);
      }
    };

    const cleanup = authEvents.on(AUTH_EVENTS.LOGIN_SUCCESS, handleLoginSuccess);
    return cleanup;
  }, [pendingNavigationPath, isAuthenticated, router]);

  // Listen for back-to-home event and reset selected key
  useEffect(() => {
    const handleBackToHome = () => {
      setSelectedKey("/");
    };

    const cleanup = authEvents.on(AUTH_EVENTS.BACK_TO_HOME, handleBackToHome);
    return cleanup;
  }, []);

  // Filter and sort routes based on accessibleRoutes from authorization context
  const accessibleMenuItems = useMemo((): RouteConfig[] => {
    if (!accessibleRoutes || accessibleRoutes.length === 0) {
      // If no accessibleRoutes available, show all routes (fallback)
      return [];
    }

    return ROUTE_CONFIG.filter((route) =>
      accessibleRoutes.includes(route.path)
    ).sort((a, b) => a.order - b.order);
  }, [accessibleRoutes]);

  /**
   * Create a menu item from route configuration
   * Pre-check authentication before navigation to avoid unnecessary route changes
   */
  const createMenuItem = (
    route: RouteConfig
  ): NonNullable<MenuProps["items"]>[number] => {
    return {
      key: route.path,
      icon: <route.Icon className="w-4 h-4" />,
      label: t(route.labelKey),
      onClick: () => {
        setSelectedKey(route.path);

        // Pre-check authentication - show auth prompt if user is not authenticated
        if (!isAuthenticated && !isSpeedMode && route.path !== "/") {
          setPendingNavigationPath(route.path);
          openAuthPromptModal();
          return; // Prevent navigation
        }

        router.push(route.path);
      },
    };
  };

  // Generate menu items from accessible routes
  const menuItems: MenuProps["items"] = accessibleMenuItems.map(createMenuItem);

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
