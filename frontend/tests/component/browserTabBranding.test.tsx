// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import I18nProviderWrapper from "@/components/providers/I18nProviderWrapper";
import { useGlobalConfigStore } from "@/stores/global";
import { publicAsset } from "@/lib/publicAsset";

const fixtures = vi.hoisted(() => ({
  zh: { productName: "智慧助手" },
  en: { productName: "Care Assistant" },
  pathname: "/zh/workbench",
  loading: undefined as Promise<void> | undefined,
  delayLogo: false,
  images: [] as HTMLImageElement[],
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
    loadLocaleMessages: async () => {
      await fixtures.loading;
      return {
        resourcesCustom: {
          zh: { custom: fixtures.zh },
          en: { custom: fixtures.en },
        },
      };
    },
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
  document.head.querySelectorAll("title").forEach((title) => title.remove());
  document.head
    .querySelectorAll("link[rel*='icon']")
    .forEach((link) => link.remove());
  fixtures.pathname = "/zh/workbench";
  fixtures.loading = undefined;
  fixtures.zh = { productName: "智慧助手" };
  fixtures.en = { productName: "Care Assistant" };
  fixtures.delayLogo = false;
  fixtures.images = [];
  vi.stubGlobal("Image", function () {
    const image = document.createElement("img");
    fixtures.images.push(image);
    if (!fixtures.delayLogo)
      queueMicrotask(() => image.dispatchEvent(new Event("load")));
    return image;
  });
  useGlobalConfigStore.getState().setConfig({});
});

afterEach(() => vi.unstubAllGlobals());

function expectTransparentIcons() {
  const icons =
    document.head.querySelectorAll<HTMLLinkElement>('link[rel*="icon"]');
  expect(icons).toHaveLength(3);
  for (const icon of icons) {
    expect(icon.getAttribute("href")).toMatch(/^data:image\/svg\+xml,/);
    const svg = new DOMParser().parseFromString(
      decodeURIComponent(icon.getAttribute("href")!.split(",")[1]),
      "image/svg+xml"
    ).documentElement;
    expect(svg.tagName).toBe("svg");
    expect(svg.children).toHaveLength(0);
  }
}

it("keeps browser icons transparent until the system logo finishes loading", async () => {
  fixtures.delayLogo = true;
  const view = render(
    <I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>
  );
  await screen.findByText("Ready");
  expectTransparentIcons();
  expect(fixtures.images).toHaveLength(1);
  expect(fixtures.images[0].getAttribute("src")).toBe(
    publicAsset("/modelengine-logo.png")
  );
  act(() => fixtures.images[0].dispatchEvent(new Event("load")));
  for (const icon of document.head.querySelectorAll('link[rel*="icon"]'))
    expect(icon.getAttribute("href")).toBe(
      publicAsset("/modelengine-logo.png")
    );
  fixtures.pathname = "/zh/agents";
  view.rerender(<I18nProviderWrapper locale="zh">Agents</I18nProviderWrapper>);
  expect(fixtures.images).toHaveLength(1);
  expect(document.head.querySelector('link[rel="icon"]')).toHaveAttribute(
    "href",
    publicAsset("/modelengine-logo.png")
  );
});

it("keeps failed system-logo loads transparent without using a default icon", async () => {
  fixtures.delayLogo = true;
  render(<I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>);
  await screen.findByText("Ready");
  expect(fixtures.images).toHaveLength(1);
  act(() => fixtures.images[0].dispatchEvent(new Event("error")));
  expectTransparentIcons();
});

it("detaches the logo preload callback when the branding provider unmounts", async () => {
  fixtures.delayLogo = true;
  const view = render(
    <I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>
  );
  await screen.findByText("Ready");
  expect(fixtures.images).toHaveLength(1);
  const image = fixtures.images[0];
  expect(image.onload).not.toBeNull();
  view.unmount();
  expect(image.onload).toBeNull();
  act(() => image.dispatchEvent(new Event("load")));
  expect(document.head.querySelectorAll('link[rel*="icon"]')).toHaveLength(0);
});

it("uses only system branding for browser tabs despite homepage or legacy overrides", async () => {
  const view = render(
    <I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>
  );
  await screen.findByText("Ready");
  act(() =>
    useGlobalConfigStore.getState().setConfig({
      productName: "System brand",
      homeTitle: "Homepage title",
      homeLogo: "home-logo.jpg?v=abc123",
      tabTitle: "Legacy title",
      tabLogo: "browser-tab-logo.png?v=abc",
    })
  );
  expect(document.title).toBe("System brand");
  for (const link of document.head.querySelectorAll("link[rel*='icon']")) {
    expect(link.getAttribute("href")).toBe(
      publicAsset("/modelengine-logo.png")
    );
  }
  fixtures.pathname = "/zh/models";
  view.rerender(<I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>);
  expect(document.title).toBe("System brand");
  act(() =>
    useGlobalConfigStore
      .getState()
      .setConfig({ productName: "System brand", tabTitle: "  ", tabLogo: "" })
  );
  expect(document.title).toBe("System brand");
  expect(document.head.querySelector("link[rel='icon']")).toHaveAttribute(
    "href",
    publicAsset("/modelengine-logo.png")
  );
});

it("ignores all homepage image settings when choosing the system favicon", async () => {
  render(<I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>);
  await screen.findByText("Ready");
  act(() =>
    useGlobalConfigStore
      .getState()
      .setConfig({ homeLogo: "home-logo.png?v=abc" })
  );
  const icon = document.head.querySelector("link[rel='icon']")!;
  expect(icon).toHaveAttribute("href", publicAsset("/modelengine-logo.png"));
  act(() =>
    useGlobalConfigStore
      .getState()
      .setConfig({ homeLogo: "https://untrusted.example/image.png" })
  );
  expect(icon).toHaveAttribute("href", publicAsset("/modelengine-logo.png"));
});

it("retains the configured title across login content and sidebar route transitions", async () => {
  const view = render(
    <I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>
  );
  await screen.findByText("Ready");
  for (const pathname of [
    "/zh/workbench",
    "/zh/agents",
    "/zh/resource-manage",
  ]) {
    fixtures.pathname = pathname;
    view.rerender(
      <I18nProviderWrapper locale="zh">{pathname}</I18nProviderWrapper>
    );
    await screen.findByText(pathname);
    expect(document.title).toBe("智慧助手");
    expect(document.head.querySelectorAll("title")).toHaveLength(1);
  }
  view.unmount();
  render(<I18nProviderWrapper locale="zh">Signed in</I18nProviderWrapper>);
  await screen.findByText("Signed in");
  expect(document.title).toBe("智慧助手");
  expect(document.head.querySelectorAll("title")).toHaveLength(1);
});

it("renders a blank title on the server before branding is available", () => {
  const html = renderToString(
    <I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>
  );
  expect(html).toContain("<title></title>");
  expect(html).not.toContain("Nexent");
  const document = new DOMParser().parseFromString(html, "text/html");
  const icons = document.head.querySelectorAll('link[rel*="icon"]');
  expect(icons).toHaveLength(3);
  for (const icon of icons)
    expect(icon.getAttribute("href")).toMatch(/^data:image\/svg\+xml,/);
  expect(html).not.toContain("modelengine-logo.png");
});

it("leaves the title blank while branding is delayed, then displays the loaded name", async () => {
  let release!: () => void;
  fixtures.loading = new Promise<void>((resolve) => {
    release = resolve;
  });
  render(<I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>);
  try {
    expect(screen.queryByText("Ready")).toBeNull();
    expect(document.title).toBe("");
  } finally {
    await act(async () => release());
  }
  await screen.findByText("Ready");
  expect(document.title).toBe("智慧助手");
});

it("keeps the title blank when the branding request returns no system name", async () => {
  fixtures.zh = { productName: "" };
  render(<I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>);
  await screen.findByText("Ready");
  expect(document.title).toBe("");
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

it("keeps missing, empty or whitespace names blank and treats markup as text", async () => {
  render(<I18nProviderWrapper locale="zh">Ready</I18nProviderWrapper>);
  await screen.findByText("Ready");
  const configurations: Record<string, string>[] = [
    {},
    { productName: "" },
    { productName: "  " },
  ];
  for (const config of configurations) {
    act(() => useGlobalConfigStore.getState().setConfig(config));
    expect(document.title).toBe("");
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
  "omits competing title and icon declarations from %s route metadata",
  async (locale) => {
    const { generateMetadata } = await import("@/app/layout");
    const metadata = await generateMetadata({
      params: Promise.resolve({ locale }),
    });
    expect(metadata).not.toHaveProperty("title");
    expect(metadata).not.toHaveProperty("icons");
    expect(metadata.description).toBeTruthy();
  }
);
