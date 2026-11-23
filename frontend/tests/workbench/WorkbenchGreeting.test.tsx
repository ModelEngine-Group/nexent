// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { WorkbenchGreeting } from "@/features/workbench/components/WorkbenchGreeting";
import { useGlobalConfigStore } from "@/stores/global";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";

beforeEach(() => {
  useGlobalConfigStore.getState().setConfig({});
});

async function renderGreeting(locale: string) {
  const i18n = createInstance();
  await i18n.use(initReactI18next).init({
    lng: locale,
    fallbackLng: "zh",
    resources: { zh: { common: zh }, en: { common: en } },
    defaultNS: "common",
    interpolation: { escapeValue: false },
  });
  render(
    <I18nextProvider i18n={i18n}>
      <WorkbenchGreeting />
    </I18nextProvider>
  );
  return i18n;
}

it.each([
  ["zh", "你好，我是医疗助手 需要我帮你做什么"],
  ["en", "Hi, I'm 医疗助手 What can I help you with"],
])("uses the global product name in %s", async (locale, expected) => {
  useGlobalConfigStore.getState().setConfig({ productName: "医疗助手" });
  await renderGreeting(locale);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(expected);
  expect(screen.getByRole("heading")).not.toHaveTextContent("Nexent");
});

it("falls back for missing/empty config and follows store and locale updates", async () => {
  const i18n = await renderGreeting("zh");
  const heading = screen.getByRole("heading");
  expect(heading).toHaveTextContent("你好，我是Nexent");
  act(() => {
    useGlobalConfigStore.getState().setConfig({ productName: "" });
  });
  expect(heading).toHaveTextContent("你好，我是Nexent");
  act(() => {
    useGlobalConfigStore.getState().setConfig({ productName: "智慧助手" });
  });
  expect(heading).toHaveTextContent("你好，我是智慧助手");
  await act(async () => {
    useGlobalConfigStore
      .getState()
      .setConfig({ productName: "Care Assistant" });
    await i18n.changeLanguage("en");
  });
  expect(heading).toHaveTextContent(
    "Hi, I'm Care Assistant What can I help you with"
  );
  act(() => {
    useGlobalConfigStore.getState().setConfig({});
  });
  expect(heading).toHaveTextContent("Hi, I'm Nexent");
});

it("renders configured special characters literally as text", async () => {
  const productName = "<b>Care & Health</b> $& {{other}}";
  useGlobalConfigStore.getState().setConfig({ productName });
  await renderGreeting("en");
  const heading = screen.getByRole("heading");
  expect(heading).toHaveTextContent(`Hi, I'm ${productName}`);
  expect(heading.querySelector("b")).toBeNull();
  expect(heading).not.toHaveTextContent("&amp;");
});
