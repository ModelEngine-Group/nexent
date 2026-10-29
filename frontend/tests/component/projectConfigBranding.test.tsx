// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { message } from "antd";
import ProjectConfigTab from "@/app/resource-manage/components/resources/projectConfig";
import {
  useGlobalConfigStore,
  useGlobalConfigStoreAllLanguage,
} from "@/stores/global";
import zh from "@/public/locales/zh/common.json";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (zh as unknown as Record<string, string>)[key] || key,
  }),
}));
vi.mock(
  "@/app/resource-manage/components/resources/PlatformQuotaPanel",
  () => ({ PlatformQuotaPanel: () => null })
);
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { config: { projectConfig: "/api/config/project-config" } },
  ApiError: class extends Error {
    constructor(
      public status: number,
      message: string
    ) {
      super(message);
    }
  },
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

beforeEach(() => {
  useGlobalConfigStore.getState().setConfig({
    productName: "System",
    homeLogo: "home-logo.png?v=abc",
  });
  const custom = {
    productName: "System",
    pageSubtitle: "Subtitle",
    pageDescription: "Description",
    homeTitle: "",
  };
  useGlobalConfigStoreAllLanguage
    .getState()
    .setAllConfig({ zh: { custom }, en: { custom: { ...custom } } });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  vi.spyOn(message, "success").mockImplementation(() => (() => {}) as never);
  vi.spyOn(message, "error").mockImplementation(() => (() => {}) as never);
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:home-preview"),
      revokeObjectURL: vi.fn(),
    })
  );
});

it("saves optional localized homepage titles and explicit empty system names", async () => {
  render(<ProjectConfigTab />);
  fireEvent.change(screen.getByRole("textbox", { name: "系统名" }), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "首页标题" }), {
    target: { value: "独立首页" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "首页标题-English" }), {
    target: { value: "Separate homepage" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const body = vi.mocked(fetch).mock.calls[0][1]!.body as FormData;
  expect(JSON.parse(body.get("configZh") as string)).toMatchObject({
    productName: "",
    homeTitle: "独立首页",
  });
  expect(JSON.parse(body.get("configEn") as string)).toMatchObject({
    productName: "System",
    homeTitle: "Separate homepage",
  });
  expect(body.get("removeHomeLogo")).toBe("false");
});

it("explicitly resets an existing homepage logo without uploading the system logo", async () => {
  render(<ProjectConfigTab />);
  fireEvent.click(screen.getByRole("button", { name: "恢复系统logo" }));
  expect(screen.getByRole("img", { name: "首页logo" })).toHaveAttribute(
    "src",
    "/modelengine-logo.png"
  );
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const body = vi.mocked(fetch).mock.calls[0][1]!.body as FormData;
  expect(body.get("removeHomeLogo")).toBe("true");
  expect(body.has("homeLogo")).toBe(false);
  expect(body.has("logo2")).toBe(false);
});

it("keeps an empty homepage title instead of substituting the system name", async () => {
  render(<ProjectConfigTab />);
  expect(screen.getByRole("textbox", { name: "首页标题" })).toHaveValue("");
  expect(screen.getByRole("textbox", { name: "系统名" })).toHaveValue("System");
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const body = vi.mocked(fetch).mock.calls[0][1]!.body as FormData;
  expect(JSON.parse(body.get("configZh") as string)).toMatchObject({
    productName: "System",
    homeTitle: "",
  });
});

it("uploads a separate image and keeps errors recoverable", async () => {
  const view = render(<ProjectConfigTab />);
  const file = new File(["png fixture"], "home.png", { type: "image/png" });
  fireEvent.change(view.container.querySelectorAll("input[type=file]")[1], {
    target: { files: [file] },
  });
  await waitFor(() =>
    expect(screen.getByRole("img", { name: "首页logo" })).toHaveAttribute(
      "src",
      "blob:home-preview"
    )
  );
  vi.mocked(fetch).mockResolvedValueOnce({
    ok: false,
    status: 400,
    json: async () => ({ message: "invalid image" }),
  } as Response);
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(message.error).toHaveBeenCalled());
  const body = vi.mocked(fetch).mock.calls[0][1]!.body as FormData;
  expect(body.get("homeLogo")).toBe(file);
  expect(screen.getByRole("button", { name: "保存" })).toBeEnabled();
});

it("rejects unsupported and oversized images without sending them", async () => {
  const view = render(<ProjectConfigTab />);
  const input = view.container.querySelectorAll("input[type=file]")[1];
  fireEvent.change(input, {
    target: {
      files: [new File(["svg"], "bad.svg", { type: "image/svg+xml" })],
    },
  });
  await waitFor(() =>
    expect(message.error).toHaveBeenCalledWith(zh["project.config.logo.format"])
  );
  fireEvent.change(view.container.querySelectorAll("input[type=file]")[1], {
    target: {
      files: [
        new File([new Uint8Array(200 * 1024 + 1)], "big.png", {
          type: "image/png",
        }),
      ],
    },
  });
  await waitFor(() =>
    expect(message.error).toHaveBeenCalledWith(zh["project.config.logo.size"])
  );
  expect(fetch).not.toHaveBeenCalled();
});
