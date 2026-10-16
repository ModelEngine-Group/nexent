// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Button, Form } from "antd";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import { UserIdentity } from "@/components/auth/UserIdentity";
import { UserIdentityInput } from "@/components/auth/UserIdentityInput";
import { UserIdentityLabel } from "@/components/auth/UserIdentityLabel";
import { getUserDisplayName } from "@/lib/userIdentity";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
const session = vi.hoisted(() => ({
  provider: "cas" as string | undefined,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: session.provider } }),
}));
describe("CAS presentation values", () => {
  it.each([
    {
      locale: "zh",
      casLabels: ["用户名", "用户名", "所属用户名", "创建人用户名"],
      emailLabels: ["邮箱", "邮箱", "所属用户邮箱", "创建人邮箱"],
    },
    {
      locale: "en",
      casLabels: ["Username", "Username", "Owner Username", "Creator Username"],
      emailLabels: ["Email", "Email", "Owner Email", "Creator Email"],
    },
  ])(
    "keeps $locale identity headers consistent with viewer changes",
    async ({ locale, casLabels, emailLabels }) => {
      const i18n = createInstance();
      await i18n.init({
        lng: locale,
        resources: { zh: { common: zh }, en: { common: en } },
        defaultNS: "common",
        keySeparator: false,
        interpolation: { escapeValue: false },
      });
      expect(i18n.t("tenantResources.users.searchUsernameOrEmail")).toBe(
        locale === "zh" ? "搜索用户名" : "Search username"
      );
      const view = () => (
        <I18nextProvider i18n={i18n}>
          <table>
            <thead>
              <tr>
                <th>
                  <UserIdentityLabel emailLabelKey="common.email" />
                </th>
                <th>
                  <UserIdentityLabel emailLabelKey="tenantResources.users.email" />
                </th>
                <th>
                  <UserIdentityLabel
                    emailLabelKey="tenantResources.apiKeys.ownerEmail"
                    usernameLabelKey="tenantResources.apiKeys.ownerUsername"
                  />
                </th>
                <th>
                  <UserIdentityLabel
                    emailLabelKey="tenantResources.apiKeys.creatorEmail"
                    usernameLabelKey="tenantResources.apiKeys.creatorUsername"
                  />
                </th>
              </tr>
            </thead>
          </table>
        </I18nextProvider>
      );
      session.provider = "cas";
      const { rerender } = render(view());
      expect(
        screen.getAllByRole("columnheader").map((header) => header.textContent)
      ).toEqual(casLabels);
      for (const provider of ["local", undefined, "cas"]) {
        session.provider = provider;
        rerender(view());
        expect(
          screen
            .getAllByRole("columnheader")
            .map((header) => header.textContent)
        ).toEqual(provider === "cas" ? casLabels : emailLabels);
      }
    }
  );
  it.each([
    ["cas", " 用户 ", "mail@test", "用户"],
    ["local", "用户", "mail@test", "mail@test"],
    [undefined, "用户", "mail@test", "mail@test"],
    ["cas", undefined, "mail@test", "mail@test"],
    ["cas", " \t", "mail@test", "mail@test"],
    ["cas", "", "—", "—"],
    ["local", "用户", " 原值 ", " 原值 "],
  ])(
    "preserves the fallback for %s/%s",
    (provider, name, fallback, expected) => {
      expect(getUserDisplayName(provider, name, fallback)).toBe(expected);
    }
  );
  it("responds to viewer changes without rewriting the record", () => {
    session.provider = "cas";
    const { rerender } = render(
      <UserIdentity casUsername="用户名" fallback="raw@test" />
    );
    expect(screen.getByText("用户名")).toBeInTheDocument();
    session.provider = "local";
    rerender(<UserIdentity casUsername="用户名" fallback="raw@test" />);
    expect(screen.getByText("raw@test")).toBeInTheDocument();
  });
  it("keeps the original form value on save while displaying the CAS name", async () => {
    session.provider = "cas";
    const save = vi.fn();
    render(
      <Form initialValues={{ username: "raw@test" }} onFinish={save}>
        <Form.Item name="username">
          <UserIdentityInput disabled casUsername="用户名" />
        </Form.Item>
        <Button htmlType="submit">Save</Button>
      </Form>
    );
    expect(screen.getByRole("textbox")).toHaveValue("用户名");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ username: "raw@test" })
    );
  });
});
