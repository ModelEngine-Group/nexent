// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import {
  DeploymentProvider,
  useDeployment,
} from "@/components/providers/deploymentProvider";
import { APP_VERSION } from "@/const/constants";
import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";

vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: vi.fn(),
}));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: {
    tenantConfig: {
      deploymentVersion: "/api/tenant_config/deployment_version",
    },
  },
  fetchWithErrorHandling: vi.fn(),
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

const request = vi.mocked(fetchWithErrorHandling);

function setAuthenticated(isAuthenticated: boolean, isAuthChecking = false) {
  vi.mocked(useAuthenticationContext).mockReturnValue({
    isAuthenticated,
    isAuthChecking,
  } as ReturnType<typeof useAuthenticationContext>);
}

function deploymentResponse() {
  return Response.json({
    app_version: "v-test",
    deployment_version: "full",
    enable_agent_workbench: true,
  });
}

function DeploymentStatus() {
  const { isDeploymentReady, appVersion, enableAgentWorkbench } =
    useDeployment();
  return (
    <div role="status">
      {isDeploymentReady ? `${appVersion} ${enableAgentWorkbench}` : "Loading"}
    </div>
  );
}

function App() {
  return (
    <DeploymentProvider>
      <DeploymentStatus />
    </DeploymentProvider>
  );
}

describe("deployment configuration authentication", () => {
  beforeEach(() => {
    request.mockReset();
    setAuthenticated(false);
  });

  it("renders guest defaults and fetches only after login", async () => {
    setAuthenticated(false, true);
    request.mockResolvedValue(deploymentResponse());
    const { rerender } = render(<App />);

    expect(request).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Loading");

    setAuthenticated(false);
    rerender(<App />);

    expect(request).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      `${APP_VERSION} false`
    );

    setAuthenticated(true);
    rerender(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByText("v-test true")).toBeVisible();
    expect(request).toHaveBeenCalledExactlyOnceWith(
      API_ENDPOINTS.tenantConfig.deploymentVersion,
      { signal: expect.any(AbortSignal) }
    );
  });

  it("releases startup with defaults if the request fails for a restored session", async () => {
    setAuthenticated(true);
    request.mockRejectedValue(new Error("Deployment config unavailable"));
    render(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByText(`${APP_VERSION} false`)).toBeVisible();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("loads the deployment after session restoration completes", async () => {
    setAuthenticated(true, true);
    request.mockResolvedValue(deploymentResponse());
    const { rerender } = render(<App />);

    expect(request).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Loading");

    setAuthenticated(true);
    rerender(<App />);

    expect(await screen.findByText("v-test true")).toBeVisible();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("discards an in-flight response after logout and reloads after relogin", async () => {
    setAuthenticated(true);
    let completeRequest!: (response: Response) => void;
    request.mockImplementationOnce(
      () => new Promise((resolve) => (completeRequest = resolve))
    );
    const { rerender } = render(<App />);
    const signal = request.mock.calls[0][1]?.signal;

    setAuthenticated(false);
    rerender(<App />);
    expect(signal?.aborted).toBe(true);
    await act(async () => completeRequest(deploymentResponse()));
    expect(screen.getByRole("status")).toHaveTextContent(
      `${APP_VERSION} false`
    );
    expect(request).toHaveBeenCalledTimes(1);

    request.mockResolvedValueOnce(deploymentResponse());
    setAuthenticated(true);
    rerender(<App />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByText("v-test true")).toBeVisible();
    expect(request).toHaveBeenCalledTimes(2);
  });
});
