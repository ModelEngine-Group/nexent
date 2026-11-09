// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterModal } from "@/components/auth/registerModal";
import zh from "@/public/locales/zh/common.json";

const state = vi.hoisted(() => ({
  options: {
    mode: "oauth_complete",
    email: "member@example.com",
    emailReadOnly: true,
    oauthProvider: "casdoor",
    passwordRequired: false,
  },
  complete: vi.fn(),
  register: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/zh/oauth/complete",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/components/auth/CasdoorSignupButton", () => ({
  CasdoorSignupButton: () => null,
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ isSpeedMode: false }),
}));
vi.mock("@/components/providers/AuthenticationProvider", () => ({
  useAuthenticationContext: () => ({
    isRegisterModalOpen: true,
    registerModalOptions: state.options,
    isAuthenticated: false,
    closeRegisterModal: vi.fn(),
    openLoginModal: vi.fn(),
    register: state.register,
    authServiceUnavailable: false,
  }),
}));
vi.mock("@/services/oauthService", () => ({
  oauthService: { completeOAuth: state.complete },
}));

async function showModal() {
  const i18n = createInstance();
  await i18n.init({
    lng: "zh",
    resources: { zh: { common: zh } },
    defaultNS: "common",
    keySeparator: false,
  });
  return render(
    <I18nextProvider i18n={i18n}>
      <App>
        <RegisterModal />
      </App>
    </I18nextProvider>
  );
}

describe("Casdoor account completion", () => {
  beforeEach(() => {
    state.options = {
      mode: "oauth_complete",
      email: "member@example.com",
      emailReadOnly: true,
      oauthProvider: "casdoor",
      passwordRequired: false,
    };
    state.complete.mockResolvedValue({
      error: "synthetic validation response",
    });
    state.register.mockReset();
  });

  it("omits password fields and submits only account completion data", async () => {
    await showModal();
    await screen.findByText(
      "此账号仅通过 Casdoor 登录，无需设置 Nexent 密码。"
    );
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0);
    const invitation = document.getElementById("inviteCode");
    expect(invitation).not.toBeNull();
    fireEvent.change(invitation!, { target: { value: "INVITE" } });
    fireEvent.submit(document.getElementById("register-form")!);
    await waitFor(() =>
      expect(state.complete).toHaveBeenCalledWith({
        email: undefined,
        invite_code: "INVITE",
      })
    );
    expect(state.register).not.toHaveBeenCalled();
  });

  it.each(["github", "local"])(
    "keeps password fields for %s completion",
    async (provider) => {
      state.options.oauthProvider = provider;
      state.options.passwordRequired = true;
      await showModal();
      await waitFor(() =>
        expect(
          document.querySelectorAll('input[type="password"]')
        ).toHaveLength(2)
      );
    }
  );
});
