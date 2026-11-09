// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CasdoorSignupButton } from "@/components/auth/CasdoorSignupButton";
import en from "@/public/locales/en/common.json";
import zh from "@/public/locales/zh/common.json";

const service = vi.hoisted(() => ({
  getConfig: vi.fn(),
  startOAuthSignup: vi.fn(),
}));

vi.mock("@/services/oauthService", () => ({ oauthService: service }));

const enabledConfig = {
  enabled: true,
  login_mode: "button",
  providers: [{ name: "casdoor", display_name: "Casdoor", enabled: true }],
};

async function showButton(locale = "zh") {
  const i18n = createInstance();
  await i18n.init({
    lng: locale,
    resources: { en: { common: en }, zh: { common: zh } },
    defaultNS: "common",
    keySeparator: false,
    interpolation: { escapeValue: false },
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <I18nextProvider i18n={i18n}>
        <CasdoorSignupButton />
      </I18nextProvider>
    </QueryClientProvider>
  );
}

describe("Casdoor registration entry", () => {
  beforeEach(() => {
    service.getConfig.mockResolvedValue(enabledConfig);
    service.startOAuthSignup.mockReset();
  });

  it.each([
    ["zh", "使用 Casdoor 注册"],
    ["en", "Sign up with Casdoor"],
  ])(
    "shows the %s entry and starts signup without submitting the local form",
    async (locale, label) => {
      await showButton(locale);
      const button = await screen.findByRole("button", { name: label });
      expect(button).toHaveAttribute("type", "button");
      fireEvent.click(button);
      expect(service.startOAuthSignup).toHaveBeenCalledExactlyOnceWith(
        "casdoor"
      );
    }
  );

  it.each([
    { ...enabledConfig, enabled: false },
    { ...enabledConfig, login_mode: "disabled" },
    { ...enabledConfig, providers: [] },
    { ...enabledConfig, providers: [{ name: "github", enabled: true }] },
  ])("hides the entry when Casdoor is unavailable: %j", async (config) => {
    service.getConfig.mockResolvedValue(config);
    await showButton();
    await waitFor(() => expect(service.getConfig).toHaveBeenCalled());
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
