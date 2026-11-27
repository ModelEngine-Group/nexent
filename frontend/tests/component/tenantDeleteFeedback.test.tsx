// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { TFunction } from "i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TenantList } from "../../app/[locale]/resource-manage/components/UserManageComp";
import type { Tenant } from "../../services/tenantService";

const deleteTenantMock = vi.fn();
const getTenantUsersMock = vi.fn();
const onTenantsRefetchMock = vi.fn();
const onSelectMock = vi.fn();

vi.mock("../../services/tenantService", () => ({
  createTenant: vi.fn(),
  updateTenant: vi.fn(),
  deleteTenant: (...args: unknown[]) => deleteTenantMock(...args),
  getTenantUsers: (...args: unknown[]) => getTenantUsersMock(...args),
  getTenant: vi.fn(),
}));

const tenant: Tenant = { tenant_id: "t-1", tenant_name: "Tenant One" };

function setup() {
  render(
    <App>
      <TenantList
        selected={null}
        onSelect={onSelectMock}
        tenants={[tenant]}
        total={1}
        page={1}
        pageSize={20}
        totalPages={1}
        onPageChange={vi.fn()}
        onTenantsRefetch={onTenantsRefetchMock}
        loading={false}
        t={((key: string) => key) as unknown as TFunction}
        locale="en"
      />
    </App>
  );
}

async function openDeleteModal() {
  fireEvent.click(
    screen.getByRole("button", { name: "tenantResources.tenants.deleteTenant" })
  );
  return await screen.findByRole("button", { name: "common.confirm" });
}

describe("TenantList delete confirmation feedback", () => {
  beforeEach(() => {
    getTenantUsersMock.mockResolvedValue({ users: [] });
  });

  it("keeps the dialog open with inline error feedback when the delete request fails", async () => {
    setup();
    const confirmButton = await openDeleteModal();

    deleteTenantMock.mockRejectedValueOnce(new Error("runtime down"));
    fireEvent.click(confirmButton);

    // Inline failure feedback becomes visible inside the still-open dialog.
    expect(
      await screen.findByText("tenantResources.tenantDeleteFailed")
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "common.confirm" })).toBeTruthy();

    // A failed delete must not refresh the tenant list.
    expect(onTenantsRefetchMock).not.toHaveBeenCalled();
  });

  it("closes the dialog and refreshes tenants when the delete succeeds", async () => {
    setup();
    const confirmButton = await openDeleteModal();

    deleteTenantMock.mockResolvedValueOnce(undefined);
    onTenantsRefetchMock.mockResolvedValueOnce(undefined);
    fireEvent.click(confirmButton);

    await waitFor(() => expect(onTenantsRefetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "common.confirm" })
      ).toBeNull()
    );
    expect(deleteTenantMock).toHaveBeenCalledWith("t-1");
  });

  it("clears the previous inline error when a retry succeeds", async () => {
    setup();
    let confirmButton = await openDeleteModal();

    deleteTenantMock.mockRejectedValueOnce(new Error("runtime down"));
    fireEvent.click(confirmButton);
    await screen.findByText("tenantResources.tenantDeleteFailed");

    // Retry the same dialog: the error message disappears on retry start.
    confirmButton = screen.getByRole("button", { name: "common.confirm" });
    deleteTenantMock.mockResolvedValueOnce(undefined);
    onTenantsRefetchMock.mockResolvedValueOnce(undefined);
    fireEvent.click(confirmButton);

    await waitFor(() => expect(onTenantsRefetchMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("tenantResources.tenantDeleteFailed")).toBeNull();
  });
});
