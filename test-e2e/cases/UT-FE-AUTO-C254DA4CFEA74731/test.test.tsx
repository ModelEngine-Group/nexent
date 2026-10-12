import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, fireEvent, waitFor, screen } from "@testing-library/react";

const { mocks, messageApi, useApp } = vi.hoisted(() => {
  const messageApi = {
    success: vi.fn(),
    error: vi.fn(),
  };
  const mocks = {
    getQuotaConfig: vi.fn(),
    getQuotaUsage: vi.fn(),
    getPlatformOverview: vi.fn(),
    updateTenantQuota: vi.fn(),
    deleteTenantQuota: vi.fn(),
  };
  const useApp = vi.fn(() => ({ message: messageApi }));
  return { mocks, messageApi, useApp };
});

vi.mock("react-i18next", () => ({
  initReactI18next: { init: () => {} },
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "en", changeLanguage: () => Promise.resolve() },
  }),
}));

vi.mock("@ant-design/icons", () => {
  const icon = (props: any) =>
    React.createElement("span", { "data-testid": "anticon" }, props?.["aria-label"] ?? null);
  return {
    InfoCircleOutlined: icon,
    WarningOutlined: icon,
    ExclamationCircleOutlined: icon,
    CloudOutlined: icon,
    DatabaseOutlined: icon,
  };
});

vi.mock("@/services/quotaService", () => ({
  default: {
    getQuotaConfig: mocks.getQuotaConfig,
    getQuotaUsage: mocks.getQuotaUsage,
    getPlatformOverview: mocks.getPlatformOverview,
    updateTenantQuota: mocks.updateTenantQuota,
    deleteTenantQuota: mocks.deleteTenantQuota,
  },
}));

vi.mock("antd", async (importOriginal) => {
  const actual: any = await importOriginal();
  const Modal = (props: any) => {
    const footer = props.footer ?? (
      <>
        {props.cancelText !== undefined && (
          <button type="button" onClick={props.onCancel}>
            {props.cancelText}
          </button>
        )}
        {props.okText !== undefined && (
          <button type="button" onClick={props.onOk}>
            {props.okText}
          </button>
        )}
      </>
    );
    return (
      <div data-testid="modal">
        {props.children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    );
  };
  return {
    ...actual,
    message: messageApi,
    App: { useApp },
    Modal,
  };
});

import { QuotaSettingsModal } from "@/app/[locale]/resource-manage/components/resources/QuotaSettingsModal";
import { SuQuotaModal } from "@/app/[locale]/resource-manage/components/resources/SuQuotaModal";
import type {
  TenantQuotaConfig,
  QuotaUsageResponse,
  PlatformQuotaOverview,
} from "@/types/quota";

const GB = 1024 * 1024 * 1024;

function makeConfig(overrides: Partial<TenantQuotaConfig> = {}): TenantQuotaConfig {
  return {
    hard_limit_bytes: 100 * GB,
    hard_limit_readable: "100 GB",
    hard_limit_editable: true,
    warning_enabled: true,
    warning_threshold_pct: 80,
    critical_threshold_pct: 95,
    ...overrides,
  };
}

function makeUsage(overrides: Partial<QuotaUsageResponse> = {}): QuotaUsageResponse {
  return {
    total_bytes: 0,
    total_readable: "0 B",
    es_physical_bytes: null,
    es_physical_readable: null,
    kb_count: 0,
    file_count: 0,
    hard_limit_bytes: 100 * GB,
    hard_limit_readable: "100 GB",
    available_bytes: 100 * GB,
    available_readable: "100 GB",
    usage_pct: 0,
    tenant_warning_level: "normal",
    warning_enabled: true,
    warning_threshold_pct: 80,
    critical_threshold_pct: 95,
    ...overrides,
  };
}

function makeOverview(): PlatformQuotaOverview {
  return {
    platform_capacity_bytes: 1000 * GB,
    platform_capacity_readable: "1000 GB",
    tenants: [],
    total_allocated_bytes: 0,
    total_allocated_readable: "0 B",
    total_actual_bytes: 0,
    total_actual_readable: "0 B",
    total_es_physical_bytes: null,
    total_es_physical_readable: null,
    tenant_count: 1,
    oversubscription_ratio: null,
    remaining_allocatable_bytes: 1000 * GB,
    remaining_allocatable_readable: "1000 GB",
    allocation_percentage: 0,
    unmanaged_tenant_count: 0,
    capacity_management_enforced: false,
  };
}

function baseProps(overrides: Record<string, unknown> = {}) {
  return {
    open: true,
    tenantId: "tenant-1",
    onCancel: vi.fn(),
    onSuccess: vi.fn(),
    onUsageChange: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  mocks.getQuotaConfig.mockReset();
  mocks.getQuotaUsage.mockReset();
  mocks.getPlatformOverview.mockReset();
  mocks.updateTenantQuota.mockReset();
  mocks.deleteTenantQuota.mockReset();
  messageApi.success.mockReset();
  messageApi.error.mockReset();
  useApp.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("QuotaSettingsModal", () => {
  it("UT-FE-AUTO-C254DA4CFEA74731 echoes hard_limit_bytes and defaults unit/GB with loading resolved", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());

    render(<QuotaSettingsModal {...baseProps()} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    expect(input.value).toBe("100");
    expect(mocks.getQuotaConfig).toHaveBeenCalledWith("tenant-1");
    expect(mocks.getQuotaUsage).toHaveBeenCalledWith("tenant-1", true, true);
  });

  it("clears input => updateTenantQuota (warnings only) then deleteTenantQuota, no hard_limit fields", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.updateTenantQuota.mockResolvedValue(makeConfig());
    mocks.deleteTenantQuota.mockResolvedValue(undefined);

    const onSuccess = vi.fn();
    render(<QuotaSettingsModal {...baseProps({ onSuccess })} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });

    const saveButton = screen.getByRole("button", { name: "Save Settings" });
    fireEvent.click(saveButton);

    await waitFor(() => expect(mocks.deleteTenantQuota).toHaveBeenCalledWith("tenant-1"));

    expect(mocks.updateTenantQuota).toHaveBeenCalledTimes(1);
    expect(mocks.deleteTenantQuota).toHaveBeenCalledTimes(1);

    const [tenantArg, payload] = mocks.updateTenantQuota.mock.calls[0];
    expect(tenantArg).toBe("tenant-1");
    expect(payload).toEqual({
      warning_enabled: true,
      warning_threshold_pct: 80,
      critical_threshold_pct: 95,
    });
    expect("hard_limit_gb" in payload).toBe(false);
    expect("hard_limit_mb" in payload).toBe(false);

    const updateOrder = mocks.updateTenantQuota.mock.invocationCallOrder[0];
    const deleteOrder = mocks.deleteTenantQuota.mock.invocationCallOrder[0];
    expect(updateOrder).toBeLessThan(deleteOrder);
    expect(onSuccess).toHaveBeenCalled();
  });

  it("valid GB input => single updateTenantQuota with hard_limit_gb, no delete", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.updateTenantQuota.mockResolvedValue(makeConfig());

    render(<QuotaSettingsModal {...baseProps()} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "100" } });

    fireEvent.click(screen.getByRole("button", { name: "Save Settings" }));

    await waitFor(() => expect(mocks.updateTenantQuota).toHaveBeenCalledTimes(1));

    const [, payload] = mocks.updateTenantQuota.mock.calls[0];
    expect(payload.hard_limit_gb).toBe(100);
    expect("hard_limit_mb" in payload).toBe(false);
    expect(mocks.deleteTenantQuota).not.toHaveBeenCalled();
  });

  it("unit switch to MB => updateTenantQuota carries hard_limit_mb", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.updateTenantQuota.mockResolvedValue(makeConfig());

    render(<QuotaSettingsModal {...baseProps()} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    fireEvent.click(screen.getByText("MB"));
    fireEvent.change(input, { target: { value: "500" } });

    fireEvent.click(screen.getByRole("button", { name: "Save Settings" }));

    await waitFor(() => expect(mocks.updateTenantQuota).toHaveBeenCalledTimes(1));

    const [, payload] = mocks.updateTenantQuota.mock.calls[0];
    expect(payload.hard_limit_mb).toBe(500);
    expect("hard_limit_gb" in payload).toBe(false);
    expect(mocks.deleteTenantQuota).not.toHaveBeenCalled();
  });

  it("hard_limit_editable=false => disabled input/segmented, save only warning fields", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig({ hard_limit_editable: false }));
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.updateTenantQuota.mockResolvedValue(makeConfig({ hard_limit_editable: false }));

    render(<QuotaSettingsModal {...baseProps()} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    expect(input.disabled).toBe(true);

    const mbOption = screen.getByText("MB");
    const segmented = mbOption.closest(".ant-segmented");
    expect(segmented?.classList.contains("ant-segmented-disabled")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Save Settings" }));

    await waitFor(() => expect(mocks.updateTenantQuota).toHaveBeenCalledTimes(1));

    const [, payload] = mocks.updateTenantQuota.mock.calls[0];
    expect(payload).toEqual({
      warning_enabled: true,
      warning_threshold_pct: 80,
      critical_threshold_pct: 95,
    });
    expect("hard_limit_gb" in payload).toBe(false);
    expect("hard_limit_mb" in payload).toBe(false);
    expect(mocks.deleteTenantQuota).not.toHaveBeenCalled();
  });

  it("updateTenantQuota conflict maps error key, resets saving, no success", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.updateTenantQuota.mockRejectedValue({
      code: "PlatformCapacityExceeded",
      message: "platform capacity exceeded",
    });

    const onSuccess = vi.fn();
    render(<QuotaSettingsModal {...baseProps({ onSuccess })} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "100" } });

    fireEvent.click(screen.getByRole("button", { name: "Save Settings" }));

    await waitFor(() =>
      expect(messageApi.error).toHaveBeenCalledWith("quota.error.platformCapacityExceeded")
    );
    expect(messageApi.success).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
    expect(mocks.deleteTenantQuota).not.toHaveBeenCalled();

    await waitFor(() => {
      const saveButton = screen.getByRole("button", { name: "Save Settings" }) as HTMLButtonElement;
      expect(saveButton.disabled).toBe(false);
    });
  });
});

describe("SuQuotaModal", () => {
  it("cleared input => deleteTenantQuota only, no updateTenantQuota", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.getPlatformOverview.mockResolvedValue(makeOverview());
    mocks.deleteTenantQuota.mockResolvedValue(undefined);

    const onSuccess = vi.fn();
    render(<SuQuotaModal {...baseProps({ onSuccess })} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mocks.deleteTenantQuota).toHaveBeenCalledWith("tenant-1"));
    expect(mocks.updateTenantQuota).not.toHaveBeenCalled();
    expect(onSuccess).toHaveBeenCalled();
  });

  it("valid input => updateTenantQuota with hard_limit_gb, no delete", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.getPlatformOverview.mockResolvedValue(makeOverview());
    mocks.updateTenantQuota.mockResolvedValue(makeConfig());

    render(<SuQuotaModal {...baseProps()} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "100" } });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mocks.updateTenantQuota).toHaveBeenCalledTimes(1));
    const [, payload] = mocks.updateTenantQuota.mock.calls[0];
    expect(payload).toEqual({
      hard_limit_gb: 100,
      hard_limit_mb: undefined,
    });
    expect(mocks.deleteTenantQuota).not.toHaveBeenCalled();
  });

  it("deleteTenantQuota failure surfaces error, resets saving, no success", async () => {
    mocks.getQuotaConfig.mockResolvedValue(makeConfig());
    mocks.getQuotaUsage.mockResolvedValue(makeUsage());
    mocks.getPlatformOverview.mockResolvedValue(makeOverview());
    mocks.deleteTenantQuota.mockRejectedValue({
      code: "FORBIDDEN",
      message: "Tenant hard quota is managed by the platform administrator",
    });

    const onSuccess = vi.fn();
    render(<SuQuotaModal {...baseProps({ onSuccess })} />);

    const input = (await screen.findByPlaceholderText("Unlimited")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(messageApi.error).toHaveBeenCalledWith(
        "Tenant hard quota is managed by the platform administrator"
      )
    );
    expect(messageApi.success).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
