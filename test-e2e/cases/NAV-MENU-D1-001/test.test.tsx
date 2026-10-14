import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { SideNavigation } from "@/components/navigation/SideNavigation";

const state = vi.hoisted(() => ({
  routes: ["/", "/newchat", "/agents", "/agent-space", "/workbench"],
  speed: true,
  workbench: false,
  authenticated: true,
  locale: "zh",
  pathname: "/zh/agents/1",
  push: vi.fn(),
  prompt: vi.fn(),
  read: vi.fn(),
  readAll: vi.fn(),
  login: undefined as undefined | (() => void),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push }),
  usePathname: () => state.pathname,
  useParams: () => ({ locale: state.locale }),
}));
vi.mock("next/link", () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({ useAuthorizationContext: () => ({ accessibleRoutes: state.routes }) }));
vi.mock("@/components/providers/AuthenticationProvider", () => ({ useAuthenticationContext: () => ({ isAuthenticated: state.authenticated, openAuthPromptModal: state.prompt }) }));
vi.mock("@/components/providers/deploymentProvider", () => ({ useDeployment: () => ({ isSpeedMode: state.speed, enableAgentWorkbench: state.workbench }) }));
vi.mock("@/components/auth/avatarDropdown", () => ({ AvatarDropdown: () => <button>account</button> }));
vi.mock("@/lib/authEvents", () => ({ authEvents: { on: (_: string, fn: () => void) => { state.login = fn; return () => { state.login = undefined; }; } } }));
vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => ({ unreadCount: 1, items: [], isLoading: false }),
  useMarkNotificationRead: () => ({ mutateAsync: state.read }),
  useMarkAllNotificationsRead: () => ({ mutateAsync: state.readAll, isPending: false }),
}));
vi.mock("@/components/navigation/NotificationBell", () => ({ NotificationBell: ({ onMarkRead, onMarkAllRead }: { onMarkRead: (id: number) => void; onMarkAllRead: () => void }) => <><button onClick={() => onMarkRead(17)}>read notification</button><button onClick={onMarkAllRead}>read all</button></> }));

beforeEach(() => {
  state.routes = ["/", "/newchat", "/agents", "/agent-space", "/workbench"];
  state.speed = true;
  state.workbench = false;
  state.authenticated = true;
  state.locale = "zh";
  state.pathname = "/zh/agents/1";
});

test("[NAV-MENU-D1-001] children retain permissions, localized routes and nested selection", () => {
  render(<SideNavigation />);
  const nav = within(screen.getByRole("navigation"));
  expect(nav.queryByRole("button", { name: "sidebar.agentDev" })).toBeNull();
  expect(nav.queryByRole("button", { name: "sidebar.resourceSpace" })).toBeNull();
  expect(nav.queryByRole("button", { name: "sidebar.modelConfig" })).toBeNull();
  expect(nav.getByRole("button", { name: "sidebar.agentConfig" })).toHaveAttribute("aria-current", "page");
  fireEvent.click(nav.getByRole("button", { name: "sidebar.agentSpace" }));
  expect(state.push).toHaveBeenCalledWith("/zh/agent-space");
  fireEvent.click(nav.getByRole("button", { name: "sidebar.startChat" }));
  expect(state.push).toHaveBeenCalledWith("/zh/newchat");
  expect(screen.queryByRole("button", { name: "notifications.bell.label" })).toBeNull();
  expect(screen.getByRole("button", { name: "account" })).toBeVisible();
});

test("[NAV-MENU-D1-001] English chat alias and workbench feature gate remain functional", () => {
  state.locale = "en";
  state.pathname = "/en/newchat";
  const { rerender } = render(<SideNavigation />);
  expect(screen.getByRole("button", { name: "sidebar.startChat" })).toHaveAttribute("aria-current", "page");
  expect(screen.queryByRole("button", { name: "sidebar.agentWorkbench" })).toBeNull();
  state.workbench = true;
  rerender(<SideNavigation />);
  fireEvent.mouseEnter(screen.getByRole("navigation").parentElement!);
  expect(within(screen.getByRole("navigation")).getAllByRole("button").slice(0, 3).map((button) => button.textContent)).toEqual([
    "sidebar.homePage", "sidebar.agentWorkbench", "sidebar.startChat",
  ]);
  fireEvent.click(screen.getByRole("button", { name: "sidebar.agentWorkbench" }));
  expect(state.push).toHaveBeenCalledWith("/en/workbench");
  fireEvent.click(screen.getByRole("button", { name: "sidebar.agentConfig" }));
  expect(state.push).toHaveBeenCalledWith("/en/agents");
});

test("[NAV-MENU-D1-001] anonymous login interception resumes navigation and preserves home/bell", async () => {
  state.speed = false;
  state.authenticated = false;
  const { rerender } = render(<SideNavigation />);
  fireEvent.click(screen.getByRole("button", { name: "sidebar.agentConfig" }));
  expect(state.prompt).toHaveBeenCalledWith("/zh/agents");
  expect(state.push).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "notifications.bell.label" }));
  expect(state.prompt).toHaveBeenCalledWith("/");
  fireEvent.click(screen.getByRole("button", { name: "sidebar.homePage" }));
  expect(state.push).toHaveBeenCalledWith("/zh");
  state.authenticated = true;
  rerender(<SideNavigation />);
  vi.useFakeTimers();
  await act(async () => { state.login?.(); await vi.advanceTimersByTimeAsync(200); });
  vi.useRealTimers();
  expect(state.push).toHaveBeenCalledWith("/zh/agents");
});

test("[NAV-MENU-D1-001] normal notification mutations retain their arguments", async () => {
  state.speed = false;
  render(<SideNavigation />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "read notification" })); });
  expect(state.read).toHaveBeenCalledWith(17);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "read all" })); });
  expect(state.readAll).toHaveBeenCalledWith();
});
