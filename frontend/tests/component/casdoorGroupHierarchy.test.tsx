// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import GroupList from "@/app/resource-manage/components/resources/GroupList";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/auth/useUserDisplayName", () => ({
  useUserDisplayName: () => (_provider: string, fallback: string) => fallback,
}));
vi.mock("@/hooks/user/useUserList", () => ({
  useUserList: () => ({ data: { users: [] }, refetch: vi.fn() }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: (_tenant: string, page?: number) => {
    const parent = {
      group_id: 1,
      group_name: "Research",
      casdoor_managed: true,
    };
    const child = {
      group_id: 2,
      group_name: "Analytics",
      parent_group_id: 1,
      casdoor_managed: true,
    };
    return {
      data: { groups: page ? [child] : [parent, child], total: 1 },
      isLoading: false,
    };
  },
}));

it("shows a Casdoor parent even when the parent is on another page", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <GroupList tenantId="tenant" />
    </QueryClientProvider>
  );
  expect(
    screen.getByRole("columnheader", {
      name: "tenantResources.groups.parentGroup",
    })
  ).toBeVisible();
  const child = screen.getByRole("row", { name: /Analytics/ });
  expect(within(child).getByRole("cell", { name: "Research" })).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: /tenantResources.groups.createGroup/ })
  );
  const dialog = await screen.findByRole("dialog", {
    name: "tenantResources.groups.createGroup",
  });
  expect(
    within(dialog).getByRole("combobox", {
      name: "tenantResources.groups.parentGroup",
    })
  ).toBeInTheDocument();
});
