// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { SystemConfigPage } from "@/features/system-config/SystemConfigPage";
import type {
  SystemConfigurationItem,
  SystemConfigurationListResponse,
} from "@/types/systemConfiguration";

const state = vi.hoisted(() => ({
  list: vi.fn(),
  save: vi.fn(),
}));

vi.mock("@/services/systemConfigurationService", () => ({
  listSystemConfigurations: (...args: unknown[]) => state.list(...args),
  saveSystemConfigurations: (...args: unknown[]) => state.save(...args),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) => {
      const templates: Record<string, string> = {
        "systemConfig.metric.managedValue": "{{count}}",
        "systemConfig.metric.groupsValue": "{{count}}",
        "systemConfig.metric.modifiedValue": "{{count}}",
      };
      return (templates[key] ?? key).replace(
        "{{count}}",
        String(options?.count ?? "")
      );
    },
  }),
}));

vi.mock("@/components/quota/PlatformQuotaPanel", () => ({
  PlatformQuotaPanel: () => <div>Platform quota panel</div>,
}));

vi.mock("@/components/system-config/ProjectConfigTab", () => ({
  default: () => <div>Project config panel</div>,
}));

const KEYS = [
  "MAX_TENANT_COUNT",
  "MAX_USERS_PER_TENANT",
  "MAX_GROUPS_PER_TENANT",
  "MAX_ADMINS_PER_TENANT",
  "MAX_KNOWLEDGE_BASES_PER_TENANT",
  "MAX_KNOWLEDGE_BASES_PER_USER",
  "MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER",
  "MAX_KNOWLEDGE_FILE_SIZE_MB",
  "MAX_CONVERSATION_TURNS",
  "MAX_CONVERSATIONS_PER_USER",
  "MAX_MCP_SERVICES_PER_TENANT",
  "MCP_REQUEST_TIMEOUT_SECONDS",
  "MAX_EVALUATION_SET_FILE_SIZE_MB",
  "RUNTIME_MCP_TOOL_TIMEOUT_SECONDS",
  "RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS",
  "LLM_INCLUDE_LOGPROBS",
  "MAX_SKILLS_PER_TENANT",
  "MAX_SKILL_UPLOAD_SIZE_MB",
];

function item(
  key: string,
  value: number | boolean = 100
): SystemConfigurationItem {
  const kind =
    key === "LLM_INCLUDE_LOGPROBS"
      ? "boolean"
      : key.includes("TIMEOUT")
        ? "number"
        : "integer";
  return {
    key,
    value,
    default_value: value,
    kind,
    group:
      key.includes("TIMEOUT") || key === "LLM_INCLUDE_LOGPROBS"
        ? "runtime"
        : key.includes("SIZE")
          ? "upload"
          : key.includes("TENANT") || key.includes("GROUP")
            ? "tenant"
            : "capacity",
    label_key: `systemConfig.param.${key}.label`,
    description_key: `systemConfig.param.${key}.desc`,
    unit_key: key.includes("TIMEOUT") ? "systemConfig.unit.second" : null,
    effect_key: "systemConfig.effect.nextRun",
    recommendation_available: false,
  };
}

function response(): SystemConfigurationListResponse {
  return { items: KEYS.map((key) => item(key)), total: 18 };
}

function renderPage(showParameters = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <App>
        <SystemConfigPage />
      </App>
    </QueryClientProvider>
  );
  if (showParameters) {
    fireEvent.click(
      screen.getByRole("tab", { name: "systemConfig.tabs.parameters" })
    );
  }
  return view;
}

function deferred() {
  let resolve!: (value: unknown) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  state.list.mockReset();
  state.save.mockReset();
  state.list.mockResolvedValue(response());
  state.save.mockImplementation(async (changes) => ({
    saved: true,
    notification: "published",
    items: Object.entries(changes as Record<string, number | boolean>).map(
      ([key, value]) => item(key, value)
    ),
  }));
});

test("renders the exact catalog as one table without decorative panels", async () => {
  renderPage(false);

  expect(await screen.findByText("Project config panel")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "systemConfig.title", level: 1 })
  ).toBeInTheDocument();
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
    "systemConfig.title",
    "quota.platformOverview",
    "systemConfig.tabs.parameters",
  ]);
  fireEvent.click(screen.getByRole("tab", { name: "quota.platformOverview" }));
  expect(screen.getByText("Platform quota panel")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "systemConfig.title" }));
  expect(screen.getByText("Project config panel")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("tab", { name: "systemConfig.tabs.parameters" })
  );
  expect(
    await screen.findByTestId("config-row-MAX_TENANT_COUNT")
  ).toBeInTheDocument();
  expect(screen.getByText("systemConfig.subtitle")).toBeInTheDocument();
  expect(
    screen.queryByText("systemConfig.breadcrumb.ops")
  ).not.toBeInTheDocument();
  expect(screen.getByTestId("config-table")).toBeInTheDocument();
  expect(screen.getByTestId("config-content")).toHaveClass("w-full");
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(document.querySelector(".ant-card")).not.toBeInTheDocument();
  expect(screen.queryByTestId("config-summary")).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("systemConfig.searchLabel")
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "systemConfig.onlyModified" })
  ).toBeInTheDocument();
  expect(screen.getByTestId("config-page")).toHaveClass(
    "bg-[var(--color-bg-5)]"
  );
  expect(screen.getByTestId("config-filter")).not.toHaveClass("border");
  expect(screen.getByTestId("config-filter")).not.toHaveClass("shadow-sm");
  expect(
    screen.queryByText("systemConfig.hotUpdateTag")
  ).not.toBeInTheDocument();
  expect(
    screen.getAllByRole("button", { name: /detail.openFor/ })
  ).toHaveLength(10);
  expect(
    within(screen.getByTestId("config-row-MAX_TENANT_COUNT")).queryByText(
      "MAX_TENANT_COUNT"
    )
  ).not.toBeInTheDocument();
  const firstRowCells = within(
    screen.getByTestId("config-row-MAX_TENANT_COUNT")
  ).getAllByRole("cell");
  expect(firstRowCells).toHaveLength(4);
  expect(screen.getByTestId("config-value-MAX_TENANT_COUNT")).toHaveClass(
    "items-center",
    "text-center"
  );
  expect(
    screen.getByRole("columnheader", { name: "systemConfig.table.value" })
  ).toHaveStyle({ textAlign: "center" });
  expect(
    within(firstRowCells[3]).getByRole("button", {
      name: /detail.openFor/,
    })
  ).toBeInTheDocument();
  expect(screen.getAllByTestId(/^config-row-/)).toHaveLength(10);
  expect(document.querySelector(".ant-table-bordered")).not.toBeNull();
  expect(screen.getByText("common.pagination.total")).toBeInTheDocument();
  expect(screen.queryByText("systemConfig.recommend")).not.toBeInTheDocument();
  expect(
    screen.queryByText("systemConfig.details.open")
  ).not.toBeInTheDocument();
  fireEvent.click(
    document.querySelector(".ant-pagination-next button") as HTMLButtonElement
  );
  expect(screen.getAllByTestId(/^config-row-/)).toHaveLength(8);
  expect(
    screen.getByTestId("config-row-MAX_MCP_SERVICES_PER_TENANT")
  ).toBeInTheDocument();
  fireEvent.change(
    screen.getByPlaceholderText("systemConfig.searchPlaceholder"),
    {
      target: { value: "MAX_TENANT_COUNT" },
    }
  );
  expect(screen.getAllByTestId(/^config-row-/)).toHaveLength(1);
});

test("resizes system parameter columns with the keyboard", async () => {
  renderPage();
  await screen.findByTestId("config-table");

  const parameterResize = screen.getAllByRole("separator")[0];
  expect(parameterResize).toHaveAttribute("aria-valuenow", "340");
  fireEvent.keyDown(parameterResize, { key: "ArrowRight" });
  expect(parameterResize).toHaveAttribute("aria-valuenow", "356");
  fireEvent.keyDown(parameterResize, { key: "ArrowLeft" });
  expect(parameterResize).toHaveAttribute("aria-valuenow", "340");
});

test("shows the parameter key and metadata only in the detail modal", async () => {
  const baseline = item("MAX_TENANT_COUNT", 90);
  baseline.default_value = 100;
  state.list.mockResolvedValue({ items: [baseline], total: 1 });
  renderPage();

  const row = await screen.findByTestId("config-row-MAX_TENANT_COUNT");
  fireEvent.click(
    within(row).getByRole("button", { name: /systemConfig.detail.openFor/ })
  );

  expect(screen.getByRole("dialog")).toBeInTheDocument();
  const detail = await screen.findByTestId("config-detail-MAX_TENANT_COUNT");
  expect(detail).toHaveTextContent("systemConfig.detail.key");
  expect(detail).toHaveTextContent("MAX_TENANT_COUNT");
  expect(detail).toHaveTextContent("systemConfig.detail.defaultValue");
  expect(detail).toHaveTextContent("100");
  expect(detail).toHaveTextContent("systemConfig.detail.group");
  expect(detail).toHaveTextContent("systemConfig.detail.kind");
  expect(detail).toHaveTextContent("systemConfig.detail.effect");
  expect(detail).not.toHaveTextContent("systemConfig.hotUpdateTag");
});

test("shows the unsaved count only while drafts exist", async () => {
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  expect(screen.queryByTestId("config-save-bar")).not.toBeInTheDocument();
  fireEvent.change(input, { target: { value: "5" } });
  expect(screen.getByTestId("config-save-bar")).toHaveTextContent(
    "systemConfig.saveBar.count"
  );
  fireEvent.click(screen.getByRole("button", { name: /discard/ }));
  expect(screen.queryByTestId("config-save-bar")).not.toBeInTheDocument();
});

test("places the save bar inside the configuration content container", async () => {
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  fireEvent.change(input, { target: { value: "5" } });
  const saveBar = screen.getByTestId("config-save-bar");
  const filter = screen.getByTestId("config-filter");

  expect(saveBar.parentElement).toBe(filter.parentElement);
});

test("submits only changed keys and resets a field to its default", async () => {
  const baseline = item("MAX_TENANT_COUNT", 90);
  baseline.default_value = 100;
  state.list.mockResolvedValue({
    items: [baseline],
    total: 1,
  });
  state.save.mockResolvedValue({
    saved: true,
    notification: "degraded",
    items: [item("MAX_TENANT_COUNT", 100)],
  });
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  fireEvent.change(input, { target: { value: "95" } });
  fireEvent.click(
    within(await screen.findByTestId("config-row-MAX_TENANT_COUNT")).getByRole(
      "button",
      { name: /detail.openFor/ }
    )
  );
  fireEvent.click(
    await within(await screen.findByRole("dialog")).findByRole("button", {
      name: /resetDefaultFor/,
    })
  );
  fireEvent.click(screen.getByRole("button", { name: /saveBar.action/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "systemConfig.save.confirm" })
  );

  await waitFor(() =>
    expect(state.save).toHaveBeenCalledWith({ MAX_TENANT_COUNT: 100 })
  );
});

test("preserves edits made while save is pending", async () => {
  const pending = deferred();
  state.save.mockReturnValue(pending.promise);
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  fireEvent.change(input, { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: /saveBar.action/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "systemConfig.save.confirm" })
  );
  fireEvent.change(input, { target: { value: "7" } });
  await act(async () =>
    pending.resolve({
      saved: true,
      notification: "published",
      items: [item("MAX_TENANT_COUNT", 5)],
    })
  );

  await waitFor(() => expect(input).toHaveValue("7"));
  expect(screen.getByText("systemConfig.saveBar.count")).toBeInTheDocument();
});

test("keeps drafts after save failure and background refresh", async () => {
  state.save.mockRejectedValue(new Error("database unavailable"));
  state.list.mockResolvedValue({
    items: [item("MAX_TENANT_COUNT")],
    total: 1,
  });
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  fireEvent.change(input, { target: { value: "5" } });
  fireEvent.click(screen.getByRole("button", { name: /saveBar.action/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "systemConfig.save.confirm" })
  );
  await waitFor(() => expect(state.save).toHaveBeenCalled());
  expect(input).toHaveValue("5");

  state.list.mockResolvedValue({
    items: [item("MAX_TENANT_COUNT", 50)],
    total: 1,
  });
  fireEvent.click(screen.getByRole("button", { name: "systemConfig.refresh" }));
  await waitFor(() => expect(state.list).toHaveBeenCalledTimes(2));
  expect(input).toHaveValue("5");
});

test("shows a retryable query error without demo content", async () => {
  state.list.mockRejectedValue(new Error("ops unavailable"));
  renderPage();

  expect(await screen.findByText("ops unavailable")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "systemConfig.retry" })
  ).toBeInTheDocument();
  expect(screen.queryByText("systemConfig.demoBadge")).not.toBeInTheDocument();
  expect(screen.queryByTestId("config-summary")).not.toBeInTheDocument();
});

test("confirms before history navigation with unsaved changes", async () => {
  const confirmation = vi.spyOn(window, "confirm").mockReturnValue(false);
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  window.dispatchEvent(new PopStateEvent("popstate"));
  expect(confirmation).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "5" } });
  window.dispatchEvent(new PopStateEvent("popstate"));

  await waitFor(() =>
    expect(confirmation).toHaveBeenCalledWith("systemConfig.leaveWarning")
  );
  confirmation.mockRestore();
});

test("keeps cached configuration editable after a background refresh failure", async () => {
  renderPage();
  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  state.list.mockRejectedValueOnce(new Error("refresh failed"));

  fireEvent.click(screen.getByRole("button", { name: "systemConfig.refresh" }));

  expect(await screen.findByText("refresh failed")).toBeInTheDocument();
  expect(screen.getByTestId("config-row-MAX_TENANT_COUNT")).toBeInTheDocument();
  fireEvent.change(input, { target: { value: "5" } });
  expect(input).toHaveValue("5");
});
