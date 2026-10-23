// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import zh from "@/public/locales/zh/common.json";
import { a2aClientService } from "@/services/a2aService";
import A2AAgentDiscoveryModal from "@/app/agents/[agentId]/components/a2a/A2AAgentDiscoveryModal";
import NacosDiscoveryPanel from "@/app/agents/[agentId]/components/a2a/NacosDiscoveryPanel";

vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/app/agents/[agentId]/components/a2a/A2AChatModal", () => ({
  default: () => null,
}));

beforeEach(async () => {
  await i18n.use(initReactI18next).init({
    lng: "zh",
    keySeparator: false,
    resources: { zh: { common: zh } },
    defaultNS: "common",
  });
  vi.spyOn(a2aClientService, "listNacosConfigs").mockResolvedValue({
    success: true,
    data: [
      {
        id: 1,
        config_id: "config",
        name: "Test registry",
        nacos_addr: "http://nacos",
        namespace_id: "public",
        is_active: true,
      },
    ],
  });
});

afterEach(() => cleanup());

const t = (key: string) => i18n.t(key);

it.each([true, false])(
  "submits the SSL verification choice %s",
  async (verify) => {
    const operation = vi
      .spyOn(a2aClientService, "discoverFromUrl")
      .mockResolvedValue({
        success: false,
        message: "Discovery failed",
      });
    const button = await openDiscovery("url", vi.fn());
    const checkbox = screen.getByRole("checkbox", {
      name: t("a2a.discovery.sslVerify"),
    });
    expect((checkbox as HTMLInputElement).checked).toBe(true);
    if (!verify) fireEvent.click(checkbox);
    fireEvent.click(button);
    await waitFor(() =>
      expect(operation).toHaveBeenCalledWith({
        url: "https://example.com/card",
        custom_headers: undefined,
        ssl_verify: verify,
      })
    );
  }
);

async function openDiscovery(mode: "url" | "nacos", onSuccess: () => void) {
  if (mode === "url") {
    render(
      <A2AAgentDiscoveryModal
        open
        onClose={() => {}}
        onDiscoverSuccess={onSuccess}
      />
    );
    fireEvent.change(
      screen.getByPlaceholderText(
        "https://example.com/.well-known/agent-xxx.json"
      ),
      {
        target: { value: "https://example.com/card" },
      }
    );
    return screen.getByRole("button", { name: t("a2a.discovery.button") });
  }
  render(<NacosDiscoveryPanel onDiscoverSuccess={onSuccess} />);
  fireEvent.click(await screen.findByText("Test registry"));
  const names = screen.getByRole("combobox");
  fireEvent.change(names, { target: { value: "Agent" } });
  fireEvent.keyDown(names, {
    key: "Enter",
    code: "Enter",
    keyCode: 13,
    which: 13,
  });
  return screen.getByRole("button", { name: t("a2a.discovery.scan") });
}

describe.each(["url", "nacos"] as const)("%s discovery loading", (mode) => {
  it.each(["timeout", "ordinary error", "unexpected rejection"])(
    "ends loading, displays %s and allows retry",
    async (failure) => {
      let resolve!: (value: { success: false; message: string }) => void;
      let reject!: (error: Error) => void;
      const pending = new Promise<{ success: false; message: string }>(
        (done, fail) => {
          resolve = done;
          reject = fail;
        }
      );
      const operation = vi
        .spyOn(
          a2aClientService,
          mode === "url" ? "discoverFromUrl" : "discoverFromNacos"
        )
        .mockReturnValueOnce(pending);
      const onSuccess = vi.fn();
      const button = await openDiscovery(mode, onSuccess);
      fireEvent.click(button);
      await waitFor(() => expect(operation).toHaveBeenCalledTimes(1));
      expect(button.className).toContain("ant-btn-loading");
      if (mode === "url")
        expect(screen.getByText(t("a2a.discovery.discovering"))).toBeTruthy();
      const errorMessage =
        failure === "timeout"
          ? t("a2a.service.discoveryTimeout")
          : failure === "ordinary error"
            ? "Invalid Agent Card"
            : t("a2a.discovery.failed");
      await act(async () => {
        if (failure === "unexpected rejection") reject(new Error("unexpected"));
        else resolve({ success: false, message: errorMessage });
      });
      expect(await screen.findByText(errorMessage)).toBeTruthy();
      expect(button.className).not.toContain("ant-btn-loading");
      if (mode === "url")
        expect(screen.queryByText(t("a2a.discovery.discovering"))).toBeNull();
      expect(onSuccess).not.toHaveBeenCalled();

      const agent = {
        id: 1,
        name: "Agent",
        source_type: "url" as const,
        agent_url: "https://example.com",
        is_available: true,
      };
      if (mode === "url")
        operation.mockResolvedValueOnce({ success: true, data: agent });
      else operation.mockResolvedValueOnce({ success: true, data: [agent] });
      fireEvent.click(button);
      await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
      expect(operation).toHaveBeenCalledTimes(2);
      expect(button.className).not.toContain("ant-btn-loading");
    }
  );
});
