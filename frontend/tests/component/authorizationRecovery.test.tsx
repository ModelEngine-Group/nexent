// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import Homepage from "../../app/[locale]/page";
import {
  AuthorizationProvider,
  useAuthorizationContext,
} from "@/components/providers/AuthorizationProvider";
import type { AuthInfoResponse } from "@/types/auth";
import { USER_ROLES } from "@/const/auth";

const state = vi.hoisted(() => ({
  request: vi.fn<() => Promise<AuthInfoResponse | null>>(),
  replace: vi.fn(),
  push: vi.fn(),
  speed: false,
  authenticated: true,
  hideHome: true,
}));
vi.mock("next/navigation", () => {
  const router = { replace: state.replace, push: state.push };
  return { useRouter: () => router, usePathname: () => "/zh" };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (key === "page.features" ? [] : key),
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({
    isDeploymentReady: true,
    hideHomePage: state.hideHome,
    enableAgentWorkbench: true,
    isSpeedMode: state.speed,
  }),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => ({
    isAuthenticated: state.authenticated,
    isAuthChecking: false,
    openAuthPromptModal: vi.fn(),
  }),
}));
vi.mock("@/stores/global", () => ({
  useGlobalConfigStore: () => ({ config: { aboutConfig: "closed" } }),
}));
vi.mock("@/lib/session", () => ({ checkSessionValid: () => true }));
vi.mock("@/services/authService", () => ({
  authService: { getCurrentUserInfo: () => state.request() },
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: undefined }),
}));

const clients: QueryClient[] = [];
function PermissionsProbe() {
  const { permissions, isAuthzReady } = useAuthorizationContext();
  return (
    <output data-testid="permissions">
      {isAuthzReady ? permissions.join(",") : "pending"}
    </output>
  );
}
function renderHome() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthorizationProvider>
        <Homepage />
        <PermissionsProbe />
      </AuthorizationProvider>
    </QueryClientProvider>
  );
}
function response(routes = ["/", "/resource-manage"]): AuthInfoResponse {
  return {
    user: {
      id: "su",
      email: "su@example.com",
      role: USER_ROLES.SU,
      groupIds: [],
      permissions: ["resource:manage"],
      accessibleRoutes: routes,
    },
  };
}
function pendingRequest() {
  let resolve!: (value: AuthInfoResponse) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<AuthInfoResponse>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
async function retryButton() {
  return screen.findByRole("button", { name: /page.retryAuthorization/ });
}

beforeEach(() => {
  state.request.mockReset();
  state.speed = false;
  state.authenticated = true;
  state.hideHome = true;
});
afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
});

test.each([false, true])(
  "failed authorization retries and applies permissions before redirect (speed=%s)",
  async (speed) => {
    state.speed = speed;
    state.authenticated = !speed;
    const retry = pendingRequest();
    state.request
      .mockRejectedValueOnce(new Error("Network unavailable"))
      .mockReturnValueOnce(retry.promise);
    renderHome();
    fireEvent.click(await retryButton());
    await waitFor(() => expect(state.request).toHaveBeenCalledTimes(2));
    expect(await retryButton()).toBeDisabled();
    fireEvent.click(await retryButton());
    expect(state.request).toHaveBeenCalledTimes(2);
    expect(state.replace).not.toHaveBeenCalled();
    expect(screen.getByTestId("permissions")).toHaveTextContent("pending");
    await act(async () => retry.resolve(response()));
    await waitFor(() =>
      expect(state.replace).toHaveBeenCalledExactlyOnceWith("/resource-manage")
    );
    expect(screen.getByTestId("permissions")).toHaveTextContent(
      "resource:manage"
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  }
);

test("another failed retry leaves recovery available without navigation", async () => {
  state.request
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockRejectedValueOnce(new Error("Service unavailable"))
    .mockResolvedValueOnce(response(["/", "/owner-manage"]));
  renderHome();
  fireEvent.click(await retryButton());
  await waitFor(async () => expect(await retryButton()).toBeEnabled());
  expect(state.replace).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "page.authorizationError"
  );
  fireEvent.click(await retryButton());
  await waitFor(() =>
    expect(state.replace).toHaveBeenCalledExactlyOnceWith("/owner-manage")
  );
});

test.each([
  null,
  {},
  { user: {} },
  { user: { permissions: [], accessibleRoutes: null } },
])("invalid response %j is recoverable", async (invalid) => {
  state.request
    .mockResolvedValueOnce(invalid as AuthInfoResponse | null)
    .mockResolvedValueOnce(response());
  renderHome();
  const button = await retryButton();
  expect(state.replace).not.toHaveBeenCalled();
  expect(screen.getByTestId("permissions")).toHaveTextContent("pending");
  fireEvent.click(button);
  await waitFor(() =>
    expect(state.replace).toHaveBeenCalledExactlyOnceWith("/resource-manage")
  );
});

test("valid empty permissions and routes retain Home after recovery", async () => {
  const empty = response([]);
  empty.user.permissions = [];
  state.request
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockResolvedValueOnce(empty);
  renderHome();
  fireEvent.click(await retryButton());
  expect(await screen.findByText("page.title")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(state.replace).not.toHaveBeenCalled();
});

test("visible Home still offers authorization recovery", async () => {
  state.hideHome = false;
  state.request
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockResolvedValueOnce(response());
  renderHome();
  fireEvent.click(await retryButton());
  expect(await screen.findByText("page.title")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByTestId("permissions")).toHaveTextContent(
    "resource:manage"
  );
  expect(state.replace).not.toHaveBeenCalled();
});

test("guest entry ignores an unrelated authorization request error", async () => {
  state.authenticated = false;
  state.request.mockRejectedValueOnce(new Error("Session unavailable"));
  renderHome();
  await waitFor(() => expect(state.request).toHaveBeenCalled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(state.replace).toHaveBeenCalledWith("/workbench");
});
