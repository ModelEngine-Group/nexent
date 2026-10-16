// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";
import { useTranslation } from "react-i18next";
import { useParams, usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { Button, Tooltip } from "antd";
import {
  Bell,
  BookOpen,
  Blocks,
  Bot,
  Building2,
  CalendarClock,
  Code,
  Database,
  Globe,
  Home,
  LineChart,
  Puzzle,
  Pin,
  PinOff,
  Sparkles,
  FolderCog,
  Settings,
  Zap,
} from "lucide-react";

import { AvatarDropdown } from "@/components/auth/avatarDropdown";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { NotificationBell } from "@/components/navigation/NotificationBell";
import { NavigationRailLabel } from "@/components/navigation/NavigationRailLabel";
import { useGlobalConfigStore } from "@/stores/global";
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
    path: "/newchat",
    Icon: Blocks,
    labelKey: "sidebar.startChat",
    order: 1.5,
    parentKey: null,
  },
  {
    path: "/workbench",
    Icon: Zap,
    labelKey: "sidebar.agentWorkbench",
    order: 0.5,
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
    Icon: Sparkles,
    labelKey: "sidebar.skillSpace",
    order: 12,
    parentKey: "/resource-space",
  },
  {
    path: "/resource-manage",
    Icon: FolderCog,
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
  "group flex h-11 w-full shrink-0 cursor-pointer items-center overflow-hidden rounded-lg border-0 bg-transparent p-0 pr-2 text-left text-[var(--navigation-muted)] transition-colors duration-150 ease-out hover:bg-[var(--navigation-hover)] hover:text-[var(--navigation-foreground)] focus-visible:text-[var(--navigation-foreground)]";
const RAIL_ICON_CLASS = "h-5 w-5 shrink-0";
const SELECTED_ITEM_CLASS = "!bg-[var(--navigation-selected)]";

function isRouteAccessible(
  route: RouteConfig,
  accessibleRoutes: string[],
  enableAgentWorkbench: boolean
) {
  if (route.path === "/workbench" && !enableAgentWorkbench) {
    return false;
  }

  return accessibleRoutes.includes(route.path);
}

interface SideNavigationProps {
  onPinnedChange?: (pinned: boolean) => void;
}

export function SideNavigation({ onPinnedChange }: SideNavigationProps = {}) {
  const { t } = useTranslation("common");
  const { accessibleRoutes } = useAuthorizationContext();
  const { isAuthenticated, openAuthPromptModal } = useAuthenticationContext();
  const { isSpeedMode, enableAgentWorkbench, hideHomePage } = useDeployment();
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams<{ locale: string }>();
  const locale = params.locale === "en" ? "en" : "zh";
  const { config } = useGlobalConfigStore();
  const [expanded, setExpanded] = useState(false);
  const [pinned, setPinned] = useState(false);
  const suppressExpansion = useRef(false);
  const hovered = useRef(false);
  const popups = useRef({ account: false, notification: false });
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const expand = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    if (suppressExpansion.current) return;
    setExpanded(true);
  };
  const collapseLater = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    if (pinned || popups.current.account || popups.current.notification) return;
    closeTimer.current = setTimeout(() => setExpanded(false), 160);
  };
  const handlePopupChange = (
    key: "account" | "notification",
    open: boolean
  ) => {
    popups.current[key] = open;
    if (open) {
      suppressExpansion.current = false;
      expand();
    } else if (!hovered.current) collapseLater();
  };
  const togglePinned = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    const nextPinned = !pinned;
    suppressExpansion.current = !nextPinned;
    setPinned(nextPinned);
    setExpanded(nextPinned);
    onPinnedChange?.(nextPinned);
  };
  useEffect(
    () => () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
      onPinnedChange?.(false);
    },
    [onPinnedChange]
  );

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
          currentPath === route.path ||
          currentPath.startsWith(`${route.path}/`) ||
          (route.navigationPath != null &&
            (currentPath === route.navigationPath ||
              currentPath.startsWith(`${route.navigationPath}/`)))
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

    return ROUTE_CONFIG.filter(
      (route) =>
        !route.isSection &&
        !(route.path === "/" && hideHomePage) &&
        isRouteAccessible(route, accessibleRoutes, enableAgentWorkbench)
    ).sort((a, b) => a.order - b.order);
  }, [accessibleRoutes, enableAgentWorkbench, hideHomePage]);

  const handleRouteClick = (route: RouteConfig) => {
    if (route.isSection) {
      return;
    }

    const routePath = route.navigationPath || route.path;
    const navigationPath = `/${locale}${routePath === "/" ? "" : routePath}`;

    if (!isAuthenticated && !isSpeedMode && route.path !== "/") {
      setPendingNavigationPath(navigationPath);
      openAuthPromptModal(navigationPath);
      return;
    }

    router.push(navigationPath);
  };

  const notificationAction = isSpeedMode ? null : isAuthenticated ? (
    <NotificationBell
      rail
      expanded={expanded}
      onOpenChange={(open) => handlePopupChange("notification", open)}
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
      <span className="flex h-11 w-12 shrink-0 items-center justify-center">
        <Bell className={RAIL_ICON_CLASS} />
      </span>
      <NavigationRailLabel
        expanded={expanded}
        label={t("notifications.bell.label")}
      />
    </button>
  );

  return (
    <div
      data-sidebar-expanded={expanded}
      data-sidebar-pinned={pinned}
      className={`relative flex h-full flex-col bg-[lab(97.0939%_-0.108689_-0.749958)] [--navigation-hover:color-mix(in_oklab,lab(92.4476%_-0.214785_-1.49835)_70%,transparent)] [--navigation-selected:lab(92.4476%_-0.214785_-1.49835)] [--navigation-muted:lab(47.7049%_-1.02875_-9.20491)] [--navigation-foreground:lab(11.6682%_-0.113927_-10.842)] p-2 transition-[width,box-shadow] duration-[180ms] ease-out motion-reduce:transition-none ${expanded ? "w-[240px]" : "w-16"} ${expanded && !pinned ? "shadow-[8px_0_24px_rgba(0,0,0,0.16)]" : ""}`}
      onMouseEnter={() => {
        hovered.current = true;
        expand();
      }}
      onMouseLeave={() => {
        hovered.current = false;
        suppressExpansion.current = false;
        collapseLater();
      }}
      onFocusCapture={expand}
      onBlurCapture={(event) => {
        if (
          !event.currentTarget.contains(event.relatedTarget) &&
          !hovered.current
        ) {
          suppressExpansion.current = false;
          collapseLater();
        }
      }}
    >
      <span
        aria-hidden="true"
        data-sidebar-divider
        className="pointer-events-none absolute inset-y-0 right-0 w-[0.5px] bg-[rgba(25,25,25,0.15)]"
      />
      <div className="mb-2 flex h-12 w-full shrink-0 items-center">
        <Link
          href="/"
          aria-label={t("sidebar.homePage")}
          className="flex h-12 min-w-0 flex-1 items-center overflow-hidden rounded-[4px] pr-2"
        >
          <span className="flex h-12 w-12 shrink-0 items-center justify-center">
            <img
              src={publicAsset("/modelengine-logo.png")}
              alt="logo"
              className="h-10 w-10 object-contain"
            />
          </span>
          <NavigationRailLabel
            expanded={expanded}
            label={config.productName || "Nexent"}
            variant="title"
          />
        </Link>
        {expanded && (
          <Tooltip title={t(pinned ? "sidebar.unpin" : "sidebar.pin")}>
            <Button
              type="text"
              aria-label={t(pinned ? "sidebar.unpin" : "sidebar.pin")}
              aria-pressed={pinned}
              onClick={togglePinned}
              className={`!h-8 !w-8 shrink-0 !p-0 ${pinned ? "!text-[#2673e5] !bg-transparent" : "!text-[#777777]"}`}
              icon={pinned ? <PinOff size={16} /> : <Pin size={16} />}
            />
          </Tooltip>
        )}
      </div>

      <nav className="min-h-0 w-full flex-1 overflow-y-auto overflow-x-hidden">
        <div className="flex flex-col gap-2">
          {accessibleMenuItems.map((route) => {
            const Icon = route.Icon;
            const isSelected = selectedKey === route.path;

            return (
              <button
                key={route.path}
                type="button"
                aria-current={isSelected ? "page" : undefined}
                aria-label={t(route.labelKey)}
                className={`${RAIL_ITEM_CLASS} ${isSelected ? SELECTED_ITEM_CLASS : ""}`}
                onClick={() => handleRouteClick(route)}
              >
                <span className="flex h-11 w-12 shrink-0 items-center justify-center">
                  <Icon
                    className={`${RAIL_ICON_CLASS} ${isSelected ? "text-[#2673e5]" : ""}`}
                  />
                </span>
                <NavigationRailLabel
                  expanded={expanded}
                  label={t(route.labelKey)}
                  selected={isSelected}
                />
              </button>
            );
          })}
        </div>
      </nav>

      <div className="flex w-full shrink-0 flex-col gap-1">
        {notificationAction}
        <AvatarDropdown
          rail
          expanded={expanded}
          onOpenChange={(open) => handlePopupChange("account", open)}
        />
      </div>
    </div>
  );
}
