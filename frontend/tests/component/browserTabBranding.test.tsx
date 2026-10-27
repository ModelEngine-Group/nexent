// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import I18nProviderWrapper from "@/components/providers/I18nProviderWrapper";
import { useGlobalConfigStore } from "@/stores/global";
import { publicAsset } from "@/lib/publicAsset";

const fixtures = vi.hoisted(() => ({
  zh: { productName: "智慧助手" },
  en: { productName: "Care Assistant" },
  pathname: "/zh/workbench",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => fixtures.pathname,
}));
vi.mock("@/app/i18n", async () => {
  const { createInstance } = await import("i18next");
  const instance = createInstance();
  await instance.init({ lng: "zh", resources: {} });
  return {
    default: instance,
    loadLocaleMessages: async () => ({
      resourcesCustom: {
        zh: { custom: fixtures.zh },
        en: { custom: fixtures.en },
      },
    }),
  };
});
vi.mock("@/components/providers/rootProvider", () => ({
  RootProvider: () => null,
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  DeploymentProvider: () => null,
}));
vi.mock("@/app/layout.client", () => ({ ClientLayout: () => null }));

beforeEach(() => {
  document.title = "AI Agent Platform";
  fixtures.pathname = "/zh/workbench";
  useGlobalConfigStore.getState().setConfig({});
});

it("retains the configured title after navigation reapplies default metadata", async () => {
  const view = render(
    <I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>
  );
  await screen.findByText("Ready");
  document.title = "Nexent";
  fixtures.pathname = "/zh/agents";
  view.rerender(<I18nProviderWrapper locale="zh">Agents</I18nProviderWrapper>);
  await waitFor(() => expect(document.title).toBe("智慧助手"));
});

it.each(["zh", "en"])(
  "uses the loaded %s product name and follows configuration changes",
  async (locale) => {
    const view = render(
      <I18nProviderWrapper locale={locale}>Ready</I18nProviderWrapper>
    );
    await screen.findByText("Ready");
    await waitFor(() =>
      expect(document.title).toBe(
        locale === "zh" ? "智慧助手" : "Care Assistant"
      )
    );
    act(() => {
      useGlobalConfigStore.getState().setConfig({ productName: "New brand" });
    });
    expect(document.title).toBe("New brand");
    view.rerender(
      <I18nProviderWrapper locale={locale === "zh" ? "en" : "zh"}>
        Ready
      </I18nProviderWrapper>
    );
    await waitFor(() =>
      expect(document.title).toBe(
        locale === "zh" ? "Care Assistant" : "智慧助手"
      )
    );
  }
);

it("falls back for missing, empty or whitespace names and treats markup as text", async () => {
  render(<I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>);
  await screen.findByText("Ready");
  const configurations: Record<string, string>[] = [
    {},
    { productName: "" },
    { productName: "  " },
  ];
  for (const config of configurations) {
    act(() => useGlobalConfigStore.getState().setConfig(config));
    expect(document.title).toBe("Nexent");
  }
  act(() =>
    useGlobalConfigStore
      .getState()
      .setConfig({ productName: "<b>Care & Health</b>" })
  );
  expect(document.title).toBe("<b>Care & Health</b>");
  expect(document.head.querySelector("title b")).toBeNull();
});

it.each(["zh", "en"])(
  "provides the current brand and base-path-aware navigation logo in %s metadata",
  async (locale) => {
    const { generateMetadata } = await import("@/app/layout");
    const metadata = await generateMetadata({
      params: Promise.resolve({ locale }),
    });
    expect(metadata.title).toBe("Nexent");
    expect(metadata.icons).toEqual({
      icon: publicAsset("/modelengine-logo.png"),
      shortcut: publicAsset("/modelengine-logo.png"),
      apple: publicAsset("/modelengine-logo.png"),
    });
    expect(metadata.description).toBeTruthy();
  }
);
