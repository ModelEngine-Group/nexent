"use client";

import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useRouter, usePathname } from "next/navigation";
import { Menu, ConfigProvider } from "antd";
import {
  Bot,
  Globe,
  Settings,
  BookOpen,
  Database,
  Code,
  Home,
  Puzzle,
  Building2,
  Zap,
  CalendarClock,
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
  parentKey?: string | null;
}

/**
 * Processed route with children for nested menus
 */
interface ProcessedRoute extends RouteConfig {
  children: RouteConfig[];
}

/**
 * Static route configuration mapping
 * All available routes with their metadata
 */
const ROUTE_CONFIG: RouteConfig[] = [
  {
    path: "/",
    Icon: Home,
    labelKey: "sidebar.homePage",
    order: 0,
    parentKey: null,
  },
  {
    path: "/chat",
    Icon: Bot,
    labelKey: "sidebar.startChat",
    order: 1,
    parentKey: null,
  },
  {
    path: "/agent-tasks",
    Icon: CalendarClock,
    labelKey: "sidebar.agentTasks",
    order: 2,
    parentKey: null,
  },
  // Agent Development submenu
  {
    path: "/agent-dev",
    Icon: Code,
    labelKey: "sidebar.agentDev",
    order: 3,
    parentKey: null,
  },
  {
    path: "/models",
    Icon: Settings,
    labelKey: "sidebar.modelConfig",
    order: 4,
    parentKey: "/agent-dev",
  },
  {
    path: "/knowledges",
    Icon: BookOpen,
    labelKey: "sidebar.knowledgeBaseConfig",
    order: 5,
    parentKey: "/agent-dev",
  },
  {
    path: "/agents",
    Icon: Bot,
    labelKey: "sidebar.agentConfig",
    order: 6,
    parentKey: "/agent-dev",
  },
  {
    path: "/memory",
    Icon: Database,
    labelKey: "sidebar.memoryConfig",
    order: 7,
    parentKey: "/agent-dev",
  },
  // Resource Space submenu
  {
    path: "/resource-space",
    Icon: Globe,
    labelKey: "sidebar.resourceSpace",
    order: 8,
    parentKey: null,
  },
  {
    path: "/agent-space",
    Icon: Bot,
    labelKey: "sidebar.agentSpace",
    order: 9,
    parentKey: "/resource-space",
  },
  {
    path: "/mcp-space",
    Icon: Puzzle,
    labelKey: "sidebar.mcpSpace",
    order: 10,
    parentKey: "/resource-space",
  },
  {
    path: "/skill-space",
    Icon: Zap,
    labelKey: "sidebar.skillSpace",
    order: 11,
    parentKey: "/resource-space",
  },
  // Management menus
  {
    path: "/resource-manage",
    Icon: Building2,
    labelKey: "sidebar.resourceManage",
    order: 12,
    parentKey: null,
  },
  {
    path: "/owner-manage",
    Icon: Building2,
    labelKey: "sidebar.ownerManage",
    order: 13,
    parentKey: null,
  },
];

/**
 * Extract all available route paths from ROUTE_CONFIG
 */
const ROUTE_PATHS = ROUTE_CONFIG.map((route) => route.path);

/**
 * Side navigation component with collapsible menu
 * Displays main navigation items for the application based on user's accessible routes
 */
export function SideNavigation({ collapsed }: SideNavigationProps) {
  const { t } = useTranslation("common");
  const { accessibleRoutes } = useAuthorizationContext();
  const { isAuthenticated, openAuthPromptModal } = useAuthenticationContext();
  const { isSpeedMode } = useDeployment();
  const router = useRouter();
  const pathname = usePathname();

  const [selectedKey, setSelectedKey] = useState("/");
  const [openKeys, setOpenKeys] = useState<string[]>([]);
  const [pendingNavigationPath, setPendingNavigationPath] = useState<
    string | null
  >(null);
  const isCollapsed = typeof collapsed === "boolean" ? collapsed : false;

  // Find parent key for a given path
  const findParentKey = (path: string): string | null => {
    const route = ROUTE_CONFIG.find((r) => r.path === path);
    return route?.parentKey || null;
  };

  // Update selected key and expand parent menu when pathname changes
  useEffect(() => {
    const currentPath = getEffectiveRoutePath(pathname);
    const matchedKey =
      currentPath === "/newchat"
        ? "/chat"
        : ROUTE_PATHS.includes(currentPath)
          ? currentPath
          : null;
    setSelectedKey(matchedKey || "");

    // Auto-expand parent menu when visiting child page
    const parentKey = findParentKey(currentPath);
    setOpenKeys(parentKey ? [parentKey] : []);
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

    const cleanup = authEvents.on(
      AUTH_EVENTS.LOGIN_SUCCESS,
      handleLoginSuccess
    );
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
  // Build nested menu structure with parent-child relationships
  const accessibleMenuItems = useMemo((): ProcessedRoute[] => {
    if (!accessibleRoutes || accessibleRoutes.length === 0) {
      return [];
    }

    const filtered = ROUTE_CONFIG.filter((route) =>
      accessibleRoutes.includes(route.path)
    );

    // Separate root items and children
    const rootItems = filtered
      .filter((route) => !route.parentKey || route.parentKey === null)
      .sort((a, b) => a.order - b.order);

    const childrenByParent = new Map<string, RouteConfig[]>();
    filtered
      .filter((route) => route.parentKey && route.parentKey !== null)
      .sort((a, b) => a.order - b.order)
      .forEach((route) => {
        const parent = route.parentKey!;
        if (!childrenByParent.has(parent)) {
          childrenByParent.set(parent, []);
        }
        childrenByParent.get(parent)!.push(route);
      });

    // Build nested structure
    return rootItems.map((root) => ({
      ...root,
      children: childrenByParent.get(root.path) || [],
    }));
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
      label: createRouteLabel(route),
      onClick: () => {
        setSelectedKey(route.path);

        // Pre-check authentication - show auth prompt if user is not authenticated
        if (!isAuthenticated && !isSpeedMode && route.path !== "/") {
          setPendingNavigationPath(route.path);
          openAuthPromptModal(route.path);
          return; // Prevent navigation
        }

        router.push(route.path);
      },
    };
  };

  const navigateToNewChat = () => {
    setSelectedKey("/chat");

    if (!isAuthenticated && !isSpeedMode) {
      setPendingNavigationPath("/newchat");
      openAuthPromptModal("/newchat");
      return;
    }

    router.push("/newchat");
  };

  const createRouteLabel = (route: RouteConfig) => {
    if (route.path !== "/chat") {
      return t(route.labelKey);
    }

    return (
      <div className="flex w-full items-center justify-between gap-2">
        <span>{t(route.labelKey)}</span>
        <button
          type="button"
          aria-label={t("sidebar.openNewChat")}
          title={t("sidebar.openNewChat")}
          className="flex h-5 w-8 shrink-0 items-center justify-center rounded-sm text-current/70 transition-colors hover:bg-black/10 hover:text-current"
          onClick={(event) => {
            event.stopPropagation();
            navigateToNewChat();
          }}
        >
          <span className="text-[10px] font-semibold uppercase leading-none tracking-wide">new</span>
        </button>
      </div>
    );
  };

  // Build menu items from accessible routes with nested submenus
  const buildMenuItems = (): MenuProps["items"] => {
    return accessibleMenuItems.map((item) => {
      // If this item has children, create a submenu
      if (item.children && item.children.length > 0) {
        return {
          key: item.path,
          icon: <item.Icon className="w-4 h-4" />,
          label: t(item.labelKey),
          children: item.children.map((child) => ({
            key: child.path,
            icon: <child.Icon className="w-4 h-4" />,
            label: t(child.labelKey),
            onClick: () => {
              setSelectedKey(child.path);
              if (!isAuthenticated && !isSpeedMode && child.path !== "/") {
                setPendingNavigationPath(child.path);
                openAuthPromptModal(child.path);
                return;
              }
              router.push(child.path);
            },
          })),
        };
      }

      // Regular menu item
      return createMenuItem(item);
    });
  };

  const menuItems: MenuProps["items"] = buildMenuItems();

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
              openKeys={openKeys}
              onOpenChange={setOpenKeys}
              items={menuItems}
              className="bg-transparent border-r-0 h-full"
            />
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
}
