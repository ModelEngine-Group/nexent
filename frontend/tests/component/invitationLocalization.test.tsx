// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { expect, it, vi } from "vitest";

import InvitationList from "@/app/resource-manage/components/resources/InvitationList";
import en from "@/public/locales/en/common.json";
import zh from "@/public/locales/zh/common.json";

const { invitations, groups } = vi.hoisted(() => ({
  invitations: {
    items: [
      {
        invitation_id: 1,
        invitation_code: "INVITATION",
        roles: ["DEV", "OPS"],
        capacity: 1,
        used_times: 0,
        status: "DISABLE",
        tenant_id: "tenant",
      },
    ],
    total: 1,
  },
  groups: { groups: [] },
}));

vi.mock("@/hooks/invitation/useInvitationList", () => ({
  useInvitationList: () => ({ data: invitations }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: groups }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { roles: ["ADMIN"] } }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));

it("updates the invitation table and disabled status when the language changes", async () => {
  const i18n = createInstance();
  await i18n.init({
    lng: "zh",
    defaultNS: "common",
    resources: { zh: { common: zh }, en: { common: en } },
  });
  render(
    <I18nextProvider i18n={i18n}>
      <InvitationList tenantId="tenant" />
    </I18nextProvider>
  );

  expect(screen.getByRole("columnheader", { name: "邀请类型" })).toBeVisible();
  expect(screen.getByText("已停用")).toBeVisible();
  expect(screen.getByText("运维管理员")).toBeVisible();

  await act(() => i18n.changeLanguage("en"));

  expect(screen.getByRole("columnheader", { name: "Code Type" })).toBeVisible();
  expect(screen.getByText("Disabled")).toBeVisible();
  expect(screen.getByText("Operations")).toBeVisible();
});
