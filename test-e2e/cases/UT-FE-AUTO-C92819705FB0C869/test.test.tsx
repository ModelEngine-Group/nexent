import React from "react";
import { App } from "antd";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderConfigCard } from "@/app/[locale]/memory/ProviderConfigCard";
import { ProviderConfigDialog } from "@/app/[locale]/memory/ProviderConfigDialog";
import {
  createProvider,
  deleteProvider,
  listPlugins,
  listProviders,
  updateProvider,
} from "@/services/providerService";
import type { PluginInfo, ProviderConfig } from "@/services/providerService";

const i18nMock = vi.hoisted(() => ({
  t: (key: string) => key,
  i18n: { changeLanguage: () => Promise.resolve() },
}));

vi.mock("antd", async (importOriginal) => {
  const actual = (await importOriginal()) as any;
  const ReactModule = await import("react");
  const app = actual.App;
  const stableContext = {
    message: actual.message,
    notification: actual.notification,
    modal: { confirm: actual.Modal.confirm },
  };
  app.useApp = () => stableContext;
  const Select = (props: any) => {
    return ReactModule.createElement(
      "div",
      {
        className: props.disabled ? "ant-select ant-select-disabled" : "ant-select",
        "data-option-count": String((props.options ?? []).length),
      },
      ReactModule.createElement("input", {
        id: props.id,
        role: "combobox",
        readOnly: true,
        disabled: props.disabled,
        value: props.value ?? "",
        placeholder: props.placeholder,
      }),
      (props.options ?? []).map((option: any) =>
            ReactModule.createElement(
              "button",
              {
                type: "button",
                key: String(option.value),
                onClick: () => {
                  props.onChange?.(option.value);
                },
              },
              option.label,
            )
          ),
    );
  };
  return { ...actual, App: app, Select };
});
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({
    isReady: true,
    isAuthenticated: true,
    isLoading: false,
    can: () => true,
    cannot: () => false,
    canAny: () => true,
    canAll: () => true,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => i18nMock,
}));

vi.mock("@/services/providerService", () => ({
  listProviders: vi.fn(),
  listPlugins: vi.fn(),
  updateProvider: vi.fn(),
  deleteProvider: vi.fn(),
  createProvider: vi.fn(),
  testSearch: vi.fn(),
  testIngest: vi.fn(),
}));

const plugin: PluginInfo = {
  name: "weaviate",
  version: "1.2.0",
  description: "Weaviate vector store",
  implements: ["retrieve", "store"],
  config_schema: [
    { key: "endpoint", label: "Endpoint", type: "string", required: true },
    { key: "api_key", label: "API Key", type: "secret", required: true },
    { key: "batch_size", label: "Batch Size", type: "number", default: 100 },
    { key: "use_tls", label: "Use TLS", type: "boolean", default: false },
    {
      key: "distance",
      label: "Distance",
      type: "select",
      options: [
        { label: "Cosine", value: "cosine" },
        { label: "L2", value: "l2" },
      ],
      default: "cosine",
    },
  ],
};

function makeProvider(overrides: Partial<ProviderConfig> = {}): ProviderConfig {
  return {
    provider_config_id: 1,
    tenant_id: "tenant-1",
    provider_name: "weaviate-prod",
    connection_type: "plugin",
    enabled: true,
    timeout_seconds: 30,
    last_error_code: null,
    params: {
      "plugin.name": "weaviate",
      "plugin.endpoint": "http://localhost:8080",
      "plugin.api_key": "top-secret",
      "plugin.batch_size": "100",
      "plugin.use_tls": "false",
      "plugin.distance": "cosine",
    },
    create_time: "2026-01-01T00:00:00Z",
    update_time: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const SECRET_MASK = "••••••••";

function renderCard() {
  return render(
    <App>
      <ProviderConfigCard
        memoryEnabled
        topK={10}
        savingTopK={false}
        onTopKChange={() => undefined}
        onTopKSave={async () => undefined}
      />
    </App>
  );
}

function renderDialog(editing: ProviderConfig | null) {
  return render(
    <App>
      <ProviderConfigDialog
        open
        editing={editing}
        onClose={() => undefined}
        onSaved={() => undefined}
      />
    </App>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listPlugins).mockResolvedValue([plugin]);
  vi.mocked(listProviders).mockResolvedValue([]);
});

describe("ProviderConfigCard", () => {
  it("UT-FE-AUTO-C92819705FB0C869 默认 filter=all 并渲染名称、状态徽标、插件名/版本、能力标签", async () => {
    vi.mocked(listProviders).mockResolvedValue([makeProvider()]);
    renderCard();

    await waitFor(() => expect(screen.getByText("weaviate-prod")).toBeTruthy());

    expect(screen.getByText("memory.external.status.normal")).toBeTruthy();
    expect(screen.getByText("weaviate · v1.2.0")).toBeTruthy();
    expect(screen.getByText("memory.external.capability.retrieve")).toBeTruthy();
    expect(screen.getByText("memory.external.capability.store")).toBeTruthy();
  });

  it("按 last_error_code 映射状态徽标", async () => {
    const rows: Array<{ name: string; code: string | null; enabled: boolean; label: string }> = [
      { name: "p-unauthorized", code: "unauthorized", enabled: true, label: "memory.external.status.unauthorized" },
      { name: "p-forbidden", code: "forbidden", enabled: true, label: "memory.external.status.forbidden" },
      { name: "p-timeout", code: "timeout", enabled: true, label: "memory.external.status.timeout" },
      { name: "p-error", code: "some-error", enabled: true, label: "memory.external.status.error" },
      { name: "p-disabled", code: null, enabled: false, label: "memory.external.status.disabled" },
    ];
    for (const row of rows) {
      vi.mocked(listProviders).mockResolvedValue([
        makeProvider({ provider_name: row.name, last_error_code: row.code, enabled: row.enabled }),
      ]);
      const { unmount } = renderCard();
      await waitFor(() => expect(screen.getByText(row.name)).toBeTruthy());
      expect(screen.getByText(row.label)).toBeTruthy();
      unmount();
    }
  });

  it("Segmented 筛选 all/enabled/attention", async () => {
    vi.mocked(listProviders).mockResolvedValue([
      makeProvider({ provider_config_id: 1, provider_name: "normal-enabled", enabled: true, last_error_code: null }),
      makeProvider({ provider_config_id: 2, provider_name: "disabled-one", enabled: false, last_error_code: null }),
      makeProvider({ provider_config_id: 3, provider_name: "attention-one", enabled: true, last_error_code: "timeout" }),
    ]);
    renderCard();

    await waitFor(() => expect(screen.getByText("normal-enabled")).toBeTruthy());
    expect(screen.getByText("disabled-one")).toBeTruthy();
    expect(screen.getByText("attention-one")).toBeTruthy();

    await userEvent.click(screen.getByText("memory.external.filters.enabled"));
    await waitFor(() => expect(screen.getByText("normal-enabled")).toBeTruthy());
    expect(screen.queryByText("disabled-one")).toBeNull();
    expect(screen.getByText("attention-one")).toBeTruthy();

    await userEvent.click(screen.getByText("memory.external.filters.attention"));
    await waitFor(() => expect(screen.getByText("attention-one")).toBeTruthy());
    expect(screen.queryByText("normal-enabled")).toBeNull();
    expect(screen.queryByText("disabled-one")).toBeNull();
  });

  it("Switch 启停调用 updateProvider(id, { enabled }) 并替换返回值", async () => {
    const original = makeProvider({ provider_config_id: 7, enabled: true });
    const updated = makeProvider({ provider_config_id: 7, enabled: false });
    vi.mocked(listProviders).mockResolvedValue([original]);
    vi.mocked(updateProvider).mockResolvedValue(updated);
    renderCard();

    await waitFor(() => expect(screen.getByText("weaviate-prod")).toBeTruthy());
    await userEvent.click(screen.getAllByRole("switch")[0]);

    await waitFor(() => expect(updateProvider).toHaveBeenCalledWith(7, { enabled: false }));
  });

  it("Switch 失败提示 updateFailed", async () => {
    vi.mocked(listProviders).mockResolvedValue([makeProvider({ provider_config_id: 7 })]);
    vi.mocked(updateProvider).mockRejectedValue(new Error("boom"));
    renderCard();

    await waitFor(() => expect(screen.getByText("weaviate-prod")).toBeTruthy());
    await userEvent.click(screen.getAllByRole("switch")[0]);

    await waitFor(() => expect(screen.getByText("memory.external.providers.updateFailed")).toBeTruthy());
  });

  it("更多菜单删除：确认后调用 deleteProvider 并移除", async () => {
    vi.mocked(listProviders).mockResolvedValue([makeProvider({ provider_config_id: 9 })]);
    vi.mocked(deleteProvider).mockResolvedValue(undefined);
    renderCard();

    await waitFor(() => expect(screen.getByText("weaviate-prod")).toBeTruthy());
    await userEvent.click(screen.getByLabelText("memory.external.actions.more"));
    await userEvent.click(await screen.findByText("memory.external.actions.delete"));

    await waitFor(() => expect(screen.getAllByText("memory.external.providers.deleteTitle").length).toBeGreaterThan(0));
    await userEvent.click(await screen.findByRole("button", { name: "memory.external.actions.delete" }));

    await waitFor(() => expect(deleteProvider).toHaveBeenCalledWith(9));
  });

  it("插件为空时新增按钮 disabled，非空时可用并打开新增对话框", async () => {
    vi.mocked(listPlugins).mockResolvedValue([]);
    const firstRender = renderCard();

    await waitFor(() => expect(screen.getByText("memory.external.noPlugins")).toBeTruthy());
    const addButtons = screen.getAllByRole("button", { name: "memory.external.actions.add" });
    expect(addButtons.every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    firstRender.unmount();

    vi.mocked(listPlugins).mockResolvedValue([plugin]);
    const { unmount } = renderCard();
    await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: "memory.external.actions.add" });
      expect(buttons.every((button) => !(button as HTMLButtonElement).disabled)).toBe(true);
    });
    await userEvent.click(screen.getAllByRole("button", { name: "memory.external.actions.add" })[0]);
    await waitFor(() => expect(screen.getByText("memory.external.form.addTitle")).toBeTruthy());
    unmount();
  });
});

describe("ProviderConfigDialog", () => {
  it("按 config_schema 动态渲染字段并回填 default", async () => {
    renderDialog(null);

    await waitFor(() => expect(screen.getByText("memory.external.form.plugin")).toBeTruthy());
    const combo = screen.getByRole("combobox");
    await userEvent.click(combo);
    await userEvent.click(await screen.findByText("weaviate (v1.2.0)"));

    await waitFor(() => {
      expect(screen.getByLabelText(/Endpoint/)).toBeTruthy();
      expect(screen.getByLabelText(/API Key/)).toBeTruthy();
      expect(screen.getByLabelText(/Batch Size/)).toBeTruthy();
      expect(screen.getByLabelText(/Use TLS/)).toBeTruthy();
      expect(screen.getByLabelText(/Distance/)).toBeTruthy();
    });

    expect(screen.getAllByText("*").length).toBeGreaterThan(0);
  });

  it("编辑已有 provider 时 secret 回显掩码，未修改不覆盖原值，修改后提交新值", async () => {
    const existing = makeProvider({ provider_config_id: 11 });
    renderDialog(existing);

    const passwordInput = await screen.findByPlaceholderText(SECRET_MASK);
    expect((passwordInput as HTMLInputElement).value).toBe(SECRET_MASK);

    vi.mocked(updateProvider).mockResolvedValue(existing);
    await userEvent.click(screen.getByRole("button", { name: "memory.external.actions.save" }));

    await waitFor(() => expect(updateProvider).toHaveBeenCalled());
    const preserveBody = vi.mocked(updateProvider).mock.calls[0][1] as { params: Record<string, string> };
    expect(preserveBody.params).not.toHaveProperty("plugin.api_key");

    await userEvent.clear(passwordInput);
    await userEvent.type(passwordInput, "new-secret");
    await userEvent.click(screen.getByRole("button", { name: "memory.external.actions.save" }));

    await waitFor(() => expect(updateProvider).toHaveBeenCalledTimes(2));
    const changedBody = vi.mocked(updateProvider).mock.calls[1][1] as { params: Record<string, string> };
    expect(changedBody.params["plugin.api_key"]).toBe("new-secret");
  });

  it("provider_name 必填校验阻断保存", async () => {
    renderDialog(null);

    await userEvent.click(screen.getByRole("button", { name: "memory.external.actions.save" }));
    await waitFor(() => expect(screen.getByText("memory.external.form.providerNameRequired")).toBeTruthy());
    expect(createProvider).not.toHaveBeenCalled();
  });

  it("编辑态插件选择器 disabled", async () => {
    renderDialog(makeProvider({ provider_config_id: 12 }));

    await waitFor(() => {
      expect(document.querySelector(".ant-select-disabled")).toBeTruthy();
    });
  });

  it("新增走 createProvider 携带 connection_type=plugin 与 params.plugin.name", async () => {
    vi.mocked(listPlugins).mockResolvedValue([plugin]);
    vi.mocked(createProvider).mockResolvedValue(makeProvider());
    renderDialog(null);

    const combo = screen.getByRole("combobox");
    await waitFor(() => expect(listPlugins).toHaveBeenCalled());
    await act(async () => {
      await vi.mocked(listPlugins).mock.results.at(-1)?.value;
    });
    await waitFor(() => expect(combo.closest(".ant-select")?.getAttribute("data-option-count")).toBe("1"));
    await waitFor(() =>
      expect(combo.closest(".ant-select")?.className ?? "").not.toContain("ant-select-loading")
    );
    fireEvent.mouseDown(combo);
    await userEvent.click((await screen.findAllByText("weaviate (v1.2.0)"))[0]);
    await userEvent.type(screen.getByLabelText("memory.external.form.providerName"), "new-provider");
    await userEvent.type(await screen.findByLabelText(/Endpoint/), "http://localhost:8080");
    await userEvent.type(await screen.findByLabelText(/API Key/), "controlled-test-key");
    await userEvent.click(screen.getByRole("button", { name: "memory.external.actions.save" }));

    await waitFor(() => expect(createProvider).toHaveBeenCalled());
    const body = vi.mocked(createProvider).mock.calls[0][0];
    expect(body.connection_type).toBe("plugin");
    expect(body.params["plugin.name"]).toBe("weaviate");
  });

  it("保存 4xx/5xx 提示 createFailed 且不关闭、不重复提交", async () => {
    vi.mocked(listPlugins).mockResolvedValue([plugin]);
    vi.mocked(createProvider).mockRejectedValue(new Error("500"));
    renderDialog(null);

    const combo = screen.getByRole("combobox");
    await waitFor(() => expect(listPlugins).toHaveBeenCalled());
    await act(async () => {
      await vi.mocked(listPlugins).mock.results.at(-1)?.value;
    });
    await waitFor(() => expect(combo.closest(".ant-select")?.getAttribute("data-option-count")).toBe("1"));
    await waitFor(() =>
      expect(combo.closest(".ant-select")?.className ?? "").not.toContain("ant-select-loading")
    );
    fireEvent.mouseDown(combo);
    await userEvent.click((await screen.findAllByText("weaviate (v1.2.0)"))[0]);
    await userEvent.type(screen.getByLabelText("memory.external.form.providerName"), "new-provider");
    await userEvent.type(await screen.findByLabelText(/Endpoint/), "http://localhost:8080");
    await userEvent.type(await screen.findByLabelText(/API Key/), "controlled-test-key");
    await userEvent.click(screen.getByRole("button", { name: "memory.external.actions.save" }));

    await waitFor(() => expect(screen.getByText("memory.external.form.createFailed")).toBeTruthy());
    expect(createProvider).toHaveBeenCalledTimes(1);
    expect(screen.getByText("memory.external.form.addTitle")).toBeTruthy();
  });
});
