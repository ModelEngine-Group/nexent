"use client";

import { useEffect, useMemo, useState, type ComponentType } from "react";
import { useTranslation } from "react-i18next";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Bell,
  BookOpen,
  Bot,
  Building2,
  CalendarClock,
  Code,
  Database,
  Globe,
  Home,
  LineChart,
  Puzzle,
  Settings,
  Zap,
} from "lucide-react";

import { AvatarDropdown } from "@/components/auth/avatarDropdown";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { NotificationBell } from "@/components/navigation/NotificationBell";
import { AUTH_EVENTS } from "@/const/auth";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/hooks/useNotifications";
import { getEffectiveRoutePath } from "@/lib/auth";
import { authEvents } from "@/lib/authEvents";
import { publicAsset } from "@/lib/publicAsset";

interface RouteConfig {
  path: string;
  Icon: ComponentType<{ className?: string }>;
  labelKey: string;
  order: number;
  parentKey?: string | null;
  navigationPath?: string;
  isSection?: boolean;
}

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
    navigationPath: "/newchat",
  },
  {
    path: "/workbench",
    Icon: Zap,
    labelKey: "sidebar.agentWorkbench",
    order: 1.5,
    parentKey: null,
  },
  {
    path: "/agent-tasks",
    Icon: CalendarClock,
    labelKey: "sidebar.agentTasks",
    order: 2,
    parentKey: null,
  },
  {
    path: "/agent-dev",
    Icon: Code,
    labelKey: "sidebar.agentDev",
    order: 3,
    parentKey: null,
    isSection: true,
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
  {
    path: "/evaluation",
    Icon: LineChart,
    labelKey: "sidebar.agentEvaluation",
    order: 8,
    parentKey: "/agent-dev",
  },
  {
    path: "/resource-space",
    Icon: Globe,
    labelKey: "sidebar.resourceSpace",
    order: 9,
    parentKey: null,
    isSection: true,
  },
  {
    path: "/agent-space",
    Icon: Bot,
    labelKey: "sidebar.agentSpace",
    order: 10,
    parentKey: "/resource-space",
  },
  {
    path: "/mcp-space",
    Icon: Puzzle,
    labelKey: "sidebar.mcpSpace",
    order: 11,
    parentKey: "/resource-space",
  },
  {
    path: "/skill-space",
    Icon: Zap,
    labelKey: "sidebar.skillSpace",
    order: 12,
    parentKey: "/resource-space",
  },
  {
    path: "/resource-manage",
    Icon: Building2,
    labelKey: "sidebar.resourceManage",
    order: 13,
    parentKey: null,
  },
  {
    path: "/owner-manage",
    Icon: Building2,
    labelKey: "sidebar.ownerManage",
    order: 14,
    parentKey: null,
  },
];

const RAIL_ITEM_CLASS =
  "flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-[4px] border-0 bg-transparent p-2 text-[#191919]";
const MENU_ITEM_CLASS = `${RAIL_ITEM_CLASS} !h-auto min-h-12 !px-0 !py-1`;
const RAIL_ICON_CLASS = "h-5 w-5 shrink-0";
const RAIL_LABEL_CLASS =
  "w-11 max-w-11 break-words text-center text-[12px] leading-[20px] ![letter-spacing:0px] text-[#191919]";
const SELECTED_ITEM_CLASS = "!bg-[rgba(25,25,25,0.05)] !rounded-[12px]";

function isRouteAccessible(
  route: RouteConfig,
  accessibleRoutes: string[],
  enableAgentWorkbench: boolean
) {
  if (route.path === "/workbench" && !enableAgentWorkbench) {
    return false;
  }

  return (
    accessibleRoutes.includes(route.path) ||
    (route.path === "/workbench" && accessibleRoutes.includes("/chat"))
  );
}

export function SideNavigation() {
  const { t } = useTranslation("common");
  const { accessibleRoutes } = useAuthorizationContext();
  const { isAuthenticated, openAuthPromptModal } = useAuthenticationContext();
  const { isSpeedMode, enableAgentWorkbench } = useDeployment();
  const router = useRouter();
  const pathname = usePathname();

  const [pendingNavigationPath, setPendingNavigationPath] = useState<
    string | null
  >(null);

  const {
    unreadCount,
    items,
    isLoading: isNotificationsLoading,
  } = useNotifications(!isSpeedMode && isAuthenticated);
  const markNotificationReadMutation = useMarkNotificationRead();
  const markAllNotificationsReadMutation = useMarkAllNotificationsRead();

  const selectedKey = useMemo(() => {
    const currentPath = getEffectiveRoutePath(pathname);
    const matchedRoute = [...ROUTE_CONFIG]
      .sort((a, b) => b.path.length - a.path.length)
      .find(
        (route) =>
          currentPath === route.path || currentPath.startsWith(`${route.path}/`)
      );

    return matchedRoute?.isSection ? "" : matchedRoute?.path || "";
  }, [pathname]);

  useEffect(() => {
    const handleLoginSuccess = () => {
      if (pendingNavigationPath && isAuthenticated) {
        setTimeout(() => {
          router.push(pendingNavigationPath);
          setPendingNavigationPath(null);
        }, 200);
      }
    };

    return authEvents.on(AUTH_EVENTS.LOGIN_SUCCESS, handleLoginSuccess);
  }, [isAuthenticated, pendingNavigationPath, router]);

  const accessibleMenuItems = useMemo(() => {
    if (!accessibleRoutes || accessibleRoutes.length === 0) {
      return [];
    }

    return ROUTE_CONFIG.filter((route) => {
      if (route.isSection) {
        return ROUTE_CONFIG.some(
          (child) =>
            child.parentKey === route.path &&
            isRouteAccessible(child, accessibleRoutes, enableAgentWorkbench)
        );
      }

      return isRouteAccessible(route, accessibleRoutes, enableAgentWorkbench);
    }).sort((a, b) => a.order - b.order);
  }, [accessibleRoutes, enableAgentWorkbench]);

  const handleRouteClick = (route: RouteConfig) => {
    if (route.isSection) {
      return;
    }

    const navigationPath = route.navigationPath || route.path;

    if (!isAuthenticated && !isSpeedMode && route.path !== "/") {
      setPendingNavigationPath(navigationPath);
      openAuthPromptModal(navigationPath);
      return;
    }

    router.push(navigationPath);
  };

  const notificationAction =
    isAuthenticated && !isSpeedMode ? (
      <NotificationBell
        rail
        unreadCount={unreadCount}
        items={items}
        isLoading={isNotificationsLoading}
        isMarkingAllRead={markAllNotificationsReadMutation.isPending}
        onMarkRead={async (receiverId) => {
          await markNotificationReadMutation.mutateAsync(receiverId);
        }}
        onMarkAllRead={async () => {
          await markAllNotificationsReadMutation.mutateAsync();
        }}
      />
    ) : (
      <button
        type="button"
        aria-label={t("notifications.bell.label")}
        className={RAIL_ITEM_CLASS}
        onClick={() => {
          if (!isAuthenticated && !isSpeedMode) {
            openAuthPromptModal("/");
          }
        }}
      >
        <Bell className={RAIL_ICON_CLASS} />
      </button>
    );

  return (
    <div className="flex h-full w-full flex-col items-center bg-[#f0f0f0] p-2">
      <Link
        href="/"
        aria-label={t("sidebar.homePage")}
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[4px] p-2"
      >
        <img
          src={publicAsset("/modelengine-logo.png")}
          alt="logo"
          className="h-8 w-8 object-contain"
        />
      </Link>

      <nav className="min-h-0 w-12 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="flex flex-col items-center gap-[12px]">
          {accessibleMenuItems.map((route) => {
            const Icon = route.Icon;
            const isSelected = selectedKey === route.path;

            return (
              <button
                key={route.path}
                type="button"
                aria-current={isSelected ? "page" : undefined}
                className={`${MENU_ITEM_CLASS} ${isSelected ? SELECTED_ITEM_CLASS : ""}`}
                onClick={() => handleRouteClick(route)}
              >
                <Icon className={RAIL_ICON_CLASS} />
                <span className={RAIL_LABEL_CLASS}>{t(route.labelKey)}</span>
              </button>
            );
          })}
        </div>
      </nav>

      <div className="flex h-24 w-12 shrink-0 flex-col items-center">
        {notificationAction}
        <AvatarDropdown rail />
      </div>
    </div>
  );
}
