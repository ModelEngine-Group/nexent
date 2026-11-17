// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
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
  cleanup_time: "00:00",
  timezone: "Asia/Shanghai",
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
      <App>{children}</App>
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
  api.saveCleanupSchedule.mockImplementation(async (tenant, settings) => ({
    ...policy,
    tenant_id: tenant ?? null,
    ...settings,
  }));
});

describe("tenant cleanup schedule", () => {
  it("loads and saves days and switch only for the selected tenant", async () => {
    open();
    const input = await screen.findByRole("spinbutton");
    expect(input).toHaveValue("30");
    expect(api.cleanupSchedule).toHaveBeenCalledWith(
      "tenant",
      expect.any(AbortSignal)
    );
    fireEvent.change(input, { target: { value: "7" } });
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    await screen.findByText("trajectory.scheduleSaved");
    expect(api.saveCleanupSchedule).toHaveBeenCalledWith(
      "tenant",
      { enabled: true, retention_days: 7 },
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
  it("rejects empty or out of range days and never saves during loading", async () => {
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
    await screen.findByRole("switch");
    expect(screen.getByRole("switch")).not.toBeChecked();
    expect(screen.getByRole("spinbutton")).toBeDisabled();
    expect(api.saveCleanupSchedule).not.toHaveBeenCalled();
  });
  it("turns scheduled cleanup off and retains the days when reopened", async () => {
    const view = open();
    const toggle = await screen.findByRole("switch");
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    expect(screen.getByRole("spinbutton")).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    await screen.findByText("trajectory.scheduleSaved");
    expect(api.saveCleanupSchedule).toHaveBeenCalledWith(
      "tenant",
      { enabled: false, retention_days: 30 },
      expect.any(AbortSignal)
    );
    view.unmount();
    api.cleanupSchedule.mockResolvedValue({ ...policy, enabled: false });
    open();
    expect(await screen.findByRole("switch")).not.toBeChecked();
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByRole("spinbutton")).toHaveValue("30");
    await waitFor(() =>
      expect(screen.getByText("trajectory.scheduleTime")).toBeVisible()
    );
  });
  it.each(["1", "30"])("saves boundary %s days", async (value) => {
    open();
    fireEvent.change(await screen.findByRole("spinbutton"), {
      target: { value },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    await screen.findByText("trajectory.scheduleSaved");
    expect(api.saveCleanupSchedule).toHaveBeenCalledWith(
      "tenant",
      { enabled: true, retention_days: Number(value) },
      expect.any(AbortSignal)
    );
  });
  it.each(["0", "31"])("blocks invalid %s days", async (value) => {
    open();
    fireEvent.change(await screen.findByRole("spinbutton"), {
      target: { value },
    });
    expect(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    ).toBeDisabled();
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

describe("SU cleanup schedule synchronization", () => {
  function openAll() {
    return render(
      <CleanupScheduleDialog scope="su" allTenants onClose={vi.fn()} />,
      { wrapper }
    );
  }

  it("requires confirmation before syncing all tenants and preserves edits on cancel", async () => {
    api.cleanupSchedule.mockResolvedValue({
      ...policy,
      tenant_id: null,
      all_tenants: true,
      mixed: true,
      tenant_count: 2,
    });
    openAll();
    const input = await screen.findByRole("spinbutton");
    await waitFor(() =>
      expect(screen.getByText("trajectory.scheduleMixed")).toBeVisible()
    );
    expect(api.cleanupSchedule).toHaveBeenCalledWith(
      undefined,
      expect.any(AbortSignal),
      true
    );
    fireEvent.change(input, { target: { value: "7" } });
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "trajectory.syncAllTenants" })
      ).toBeVisible()
    );
    expect(api.saveCleanupSchedule).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
    expect(input).toHaveValue("7");
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "trajectory.syncAllTenants" })
    );
    await screen.findByText("trajectory.scheduleSynced");
    expect(api.saveCleanupSchedule).toHaveBeenCalledWith(
      undefined,
      { enabled: true, retention_days: 7 },
      expect.any(AbortSignal),
      true
    );
  });

  it("retains values when the all-tenant save fails", async () => {
    api.saveCleanupSchedule.mockRejectedValueOnce({
      code: "query_unavailable",
    });
    openAll();
    const input = await screen.findByRole("spinbutton");
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.saveSchedule" })
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "trajectory.syncAllTenants" })
    );
    await screen.findByText("trajectory.errors.query_unavailable");
    expect(input).toHaveValue("9");
    expect(
      screen.queryByText("trajectory.scheduleSynced")
    ).not.toBeInTheDocument();
  });
});
