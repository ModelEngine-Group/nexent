// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { SideNavigation } from "@/components/navigation/SideNavigation";

const state = vi.hoisted(() => ({ speed: true, push: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ locale: "zh" }),
  usePathname: () => "/zh/agents",
  useRouter: () => ({ push: state.push }),
}));
vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ accessibleRoutes: ["/agents", "/models"] }),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => ({
    isAuthenticated: true,
    openAuthPromptModal: vi.fn(),
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({
    isSpeedMode: state.speed,
    enableAgentWorkbench: false,
  }),
}));
vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => ({ unreadCount: 0, items: [], isLoading: false }),
  useMarkNotificationRead: () => ({ mutateAsync: vi.fn() }),
  useMarkAllNotificationsRead: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));
vi.mock("@/lib/authEvents", () => ({ authEvents: { on: () => () => {} } }));
vi.mock("@/components/auth/avatarDropdown", () => ({
  AvatarDropdown: ({
    onOpenChange,
  }: {
    onOpenChange: (open: boolean) => void;
  }) => (
    <>
      <button onClick={() => onOpenChange(true)}>open account</button>
      <button onClick={() => onOpenChange(false)}>close account</button>
    </>
  ),
}));
vi.mock("@/components/navigation/NotificationBell", () => ({
  NotificationBell: ({
    onOpenChange,
  }: {
    onOpenChange: (open: boolean) => void;
  }) => (
    <>
      <button onClick={() => onOpenChange(true)}>open notifications</button>
      <button onClick={() => onOpenChange(false)}>close notifications</button>
    </>
  ),
}));

beforeEach(() => {
  vi.useFakeTimers();
  state.speed = true;
});
afterEach(() => {
  vi.useRealTimers();
});
function setup() {
  const result = render(<SideNavigation />);
  const rail = result.container.querySelector("[data-sidebar-expanded]")!;
  return { ...result, rail };
}
test("collapsed icons retain accessible names and hover displays inline labels", () => {
  const { rail } = setup();
  const item = screen.getByRole("button", { name: "sidebar.agentConfig" });
  expect(item).toHaveTextContent("");
  expect(rail).toHaveAttribute("data-sidebar-expanded", "false");
  fireEvent.mouseEnter(rail);
  expect(rail).toHaveAttribute("data-sidebar-expanded", "true");
  expect(item).toHaveTextContent("sidebar.agentConfig");
  fireEvent.click(item);
  expect(state.push).toHaveBeenCalledWith("/zh/agents");
});
test("exit is delayed and pointer re-entry cancels pending collapse", () => {
  const { rail } = setup();
  fireEvent.mouseEnter(rail);
  fireEvent.mouseLeave(rail);
  act(() => vi.advanceTimersByTime(159));
  expect(rail).toHaveAttribute("data-sidebar-expanded", "true");
  fireEvent.mouseEnter(rail);
  act(() => vi.advanceTimersByTime(500));
  expect(rail).toHaveAttribute("data-sidebar-expanded", "true");
  fireEvent.mouseLeave(rail);
  act(() => vi.advanceTimersByTime(160));
  expect(rail).toHaveAttribute("data-sidebar-expanded", "false");
});
test.each(["account", "notifications"])(
  "open %s popup holds expansion outside the rail",
  (popup) => {
    state.speed = false;
    const { rail } = setup();
    fireEvent.mouseEnter(rail);
    fireEvent.click(screen.getByText(`open ${popup}`));
    fireEvent.mouseLeave(rail);
    act(() => vi.advanceTimersByTime(500));
    expect(rail).toHaveAttribute("data-sidebar-expanded", "true");
    fireEvent.click(screen.getByText(`close ${popup}`));
    act(() => vi.advanceTimersByTime(160));
    expect(rail).toHaveAttribute("data-sidebar-expanded", "false");
  }
);
test("keyboard focus expands and leaving the rail closes it", () => {
  const { rail } = setup();
  const item = screen.getByRole("button", { name: "sidebar.agentConfig" });
  fireEvent.focus(item);
  expect(rail).toHaveAttribute("data-sidebar-expanded", "true");
  fireEvent.blur(item, { relatedTarget: document.body });
  act(() => vi.advanceTimersByTime(160));
  expect(rail).toHaveAttribute("data-sidebar-expanded", "false");
});
test("unmount clears the pending collapse timer", () => {
  const { rail, unmount } = setup();
  fireEvent.mouseEnter(rail);
  fireEvent.mouseLeave(rail);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
