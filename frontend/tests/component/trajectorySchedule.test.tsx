// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { CleanupScheduleDialog } from "@/app/observability/components/CleanupScheduleDialog";
import { trajectoryService } from "@/services/trajectoryService";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { cleanupSchedule: vi.fn(), saveCleanupSchedule: vi.fn() },
}));
const api = vi.mocked(trajectoryService);
const policy = {
  tenant_id: "tenant",
  interval_seconds: 3600,
  enabled: true,
  retention_days: 30,
};
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
function open() {
  return render(
    <CleanupScheduleDialog
      scope="admin:tenant"
      tenantId="tenant"
      onClose={vi.fn()}
    />,
    { wrapper }
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  api.cleanupSchedule.mockResolvedValue(policy);
  api.saveCleanupSchedule.mockImplementation(async (tenant, seconds) => ({
    ...policy,
    tenant_id: tenant,
    interval_seconds: seconds,
  }));
});

describe("tenant cleanup schedule", () => {
  it("loads policy, converts minutes to seconds and saves only the selected tenant", async () => {
    open();
    const input = await screen.findByRole("spinbutton");
    expect(input).toHaveValue("60");
    expect(api.cleanupSchedule).toHaveBeenCalledWith(
      "tenant",
      expect.any(AbortSignal)
    );
    fireEvent.change(input, { target: { value: "120" } });
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    await screen.findByText("trajectory.scheduleSaved");
    expect(api.saveCleanupSchedule).toHaveBeenCalledWith(
      "tenant",
      7200,
      expect.any(AbortSignal)
    );
  });
  it("retains the edited value after a failed save and supports retry", async () => {
    api.saveCleanupSchedule.mockRejectedValueOnce({
      code: "query_unavailable",
    });
    open();
    const input = await screen.findByRole("spinbutton");
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    await screen.findByText("trajectory.errors.query_unavailable");
    expect(input).toHaveValue("5");
    fireEvent.click(screen.getByRole("button", { name: "trajectory.retry" }));
    await screen.findByText("trajectory.scheduleSaved");
    expect(api.saveCleanupSchedule).toHaveBeenCalledTimes(2);
  });
  it("rejects empty or out of range minutes and never saves during loading", async () => {
    let resolve!: (value: typeof policy) => void;
    api.cleanupSchedule.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      })
    );
    open();
    expect(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    ).toBeDisabled();
    resolve(policy);
    const input = await screen.findByRole("spinbutton");
    fireEvent.change(input, { target: { value: "" } });
    expect(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    ).toBeDisabled();
    expect(api.saveCleanupSchedule).not.toHaveBeenCalled();
  });
  it("retries failed reads and displays disabled cleanup state", async () => {
    api.cleanupSchedule.mockRejectedValueOnce({ code: "query_unavailable" });
    api.cleanupSchedule.mockResolvedValueOnce({ ...policy, enabled: false });
    open();
    await screen.findByText("trajectory.errors.query_unavailable");
    fireEvent.click(screen.getByRole("button", { name: "trajectory.retry" }));
    await screen.findByText("trajectory.scheduleDisabled");
    expect(api.saveCleanupSchedule).not.toHaveBeenCalled();
  });
  it("cancels an in flight save when the dialog unmounts", async () => {
    api.saveCleanupSchedule.mockImplementation(() => new Promise(() => {}));
    const view = open();
    await screen.findByRole("spinbutton");
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    await waitFor(() => expect(api.saveCleanupSchedule).toHaveBeenCalled());
    const signal = api.saveCleanupSchedule.mock.calls[0][2];
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
