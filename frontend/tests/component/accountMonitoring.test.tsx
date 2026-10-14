import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { useAccountMonitoring } from "@/hooks/useAccountMonitoring";

const state = vi.hoisted(() => ({
  role: "SU" as string | null,
  speed: false,
  status: {
    telemetry_enabled: true,
    dashboard_url: "https://monitoring.nexent.test",
    dashboard_allowed_roles: ["SU", "SPEED"],
  } as null | {
    telemetry_enabled: boolean;
    dashboard_url: string;
    dashboard_allowed_roles: string[];
  },
  fetch: vi.fn(),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: state.role ? { id: "user", role: state.role } : null,
  }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: state.speed }),
}));
vi.mock("@/services/monitoringService", () => ({
  monitoringService: { fetchStatus: state.fetch },
}));

beforeEach(() => {
  state.role = "SU";
  state.speed = false;
  state.status = {
    telemetry_enabled: true,
    dashboard_url: "https://monitoring.nexent.test",
    dashboard_allowed_roles: ["SU", "SPEED"],
  };
  state.fetch.mockImplementation(async () => state.status);
});

function Harness() {
  const url = useAccountMonitoring();
  return <span>{url || "hidden"}</span>;
}
function renderHook() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>
  );
  return client;
}

test.each(["SU", "SPEED"])(
  "eligible %s monitoring keeps the configured destination",
  async (role) => {
    state.role = role;
    renderHook();
    expect(
      await screen.findByText("https://monitoring.nexent.test")
    ).toBeVisible();
  }
);

test("anonymous ordinary deployment never fetches monitoring status", () => {
  state.role = null;
  renderHook();
  expect(screen.getByText("hidden")).toBeVisible();
  expect(state.fetch).not.toHaveBeenCalled();
});

test.each(["denied", "disabled", "missing-url", "null-status", "rejected"])(
  "monitoring hides the link for %s status",
  async (variant) => {
    if (variant === "denied") state.role = "USER";
    if (variant === "disabled") state.status!.telemetry_enabled = false;
    if (variant === "missing-url") state.status!.dashboard_url = "";
    if (variant === "null-status") state.status = null;
    if (variant === "rejected")
      state.fetch.mockRejectedValue(new Error("status unavailable"));
    const client = renderHook();
    await waitFor(() =>
      expect(client.getQueryCache().getAll()[0].state.status).toBe(
        variant === "rejected" ? "error" : "success"
      )
    );
    expect(screen.getByText("hidden")).toBeVisible();
  }
);

test("speed deployment retains SPEED eligibility without an ordinary user", async () => {
  state.role = null;
  state.speed = true;
  renderHook();
  expect(
    await screen.findByText("https://monitoring.nexent.test")
  ).toBeVisible();
});
