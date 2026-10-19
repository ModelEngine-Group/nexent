// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import Homepage from "../../app/[locale]/page";

const state = vi.hoisted(() => ({
  deploymentReady: true,
  hideHome: true,
  workbench: true,
  speed: false,
  authenticated: true,
  checking: false,
  authzReady: true,
  routes: ["/", "/resource-manage", "/owner-manage"],
  replace: vi.fn(),
  prompt: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: state.replace, push: vi.fn() }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (key === "page.features" ? [] : key),
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({
    isDeploymentReady: state.deploymentReady,
    hideHomePage: state.hideHome,
    enableAgentWorkbench: state.workbench,
    isSpeedMode: state.speed,
  }),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => ({
    isAuthenticated: state.authenticated,
    isAuthChecking: state.checking,
    openAuthPromptModal: state.prompt,
  }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    isAuthzReady: state.authzReady,
    accessibleRoutes: state.routes,
    canAccessRoute: (route: string) => state.routes.includes(route),
    openAuthzPromptModal: state.prompt,
  }),
}));
vi.mock("@/stores/global", () => ({
  useGlobalConfigStore: () => ({ config: { aboutConfig: "closed" } }),
}));

beforeEach(() => {
  Object.assign(state, {
    deploymentReady: true,
    hideHome: true,
    workbench: true,
    speed: false,
    authenticated: true,
    checking: false,
    authzReady: true,
    routes: ["/", "/resource-manage", "/owner-manage"],
  });
});

test("SU lands on authorized management without a denial prompt", () => {
  render(<Homepage />);
  expect(state.replace).toHaveBeenCalledExactlyOnceWith("/resource-manage");
  expect(state.prompt).not.toHaveBeenCalled();
});

test.each(["deploymentReady", "authzReady"] as const)(
  "waits until %s is ready",
  (key) => {
    state[key] = false;
    render(<Homepage />);
    expect(state.replace).not.toHaveBeenCalled();
  }
);

test("waits for authentication checking before deciding guest entry", () => {
  state.authenticated = false;
  state.checking = true;
  render(<Homepage />);
  expect(state.replace).not.toHaveBeenCalled();
});

test("redirects only after SU authorization arrives", () => {
  state.authzReady = false;
  state.routes = [];
  const { rerender } = render(<Homepage />);
  expect(state.replace).not.toHaveBeenCalled();
  state.authzReady = true;
  state.routes = ["/", "/owner-manage"];
  rerender(<Homepage />);
  expect(state.replace).toHaveBeenCalledExactlyOnceWith("/owner-manage");
});

test.each([
  { routes: ["/newchat", "/workbench"], enabled: true, target: "/workbench" },
  { routes: ["/chat", "/newchat"], enabled: true, target: "/workbench" },
  { routes: ["/newchat"], enabled: true, target: "/newchat" },
  { routes: ["/workbench", "/newchat"], enabled: false, target: "/newchat" },
  {
    routes: ["/workbench", "/owner-manage"],
    enabled: false,
    target: "/owner-manage",
  },
  {
    routes: ["/agent-dev", "/resource-space", "/models"],
    enabled: true,
    target: "/models",
  },
])(
  "selects $target for enabled=$enabled and $routes",
  ({ routes, enabled, target }) => {
    state.routes = routes;
    state.workbench = enabled;
    render(<Homepage />);
    expect(state.replace).toHaveBeenCalledExactlyOnceWith(target);
  }
);

test.each([[], ["/"], ["/agent-dev", "/resource-space"]])(
  "renders Home without self-redirect for permissions %j",
  (...routes: string[]) => {
    state.routes = routes;
    render(<Homepage />);
    expect(state.replace).not.toHaveBeenCalled();
    expect(screen.getByText("page.title")).toBeInTheDocument();
  }
);

test("retains Home when it is configured visible", () => {
  state.hideHome = false;
  render(<Homepage />);
  expect(state.replace).not.toHaveBeenCalled();
  expect(screen.getByText("page.title")).toBeInTheDocument();
});

test.each([true, false])(
  "preserves guest default entry with Workbench=%s",
  (enabled) => {
    state.authenticated = false;
    state.authzReady = false;
    state.workbench = enabled;
    render(<Homepage />);
    expect(state.replace).toHaveBeenCalledExactlyOnceWith(
      enabled ? "/workbench" : "/newchat"
    );
  }
);

test("speed mode also waits for authorization before selecting an entry", () => {
  state.authenticated = false;
  state.speed = true;
  state.authzReady = false;
  render(<Homepage />);
  expect(state.replace).not.toHaveBeenCalled();
});
