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

const KEYS = [
  "MAX_TENANT_COUNT",
  "MAX_USERS_PER_TENANT",
  "MAX_GROUPS_PER_TENANT",
  "MAX_SUPER_ADMIN_COUNT",
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
  return { items: KEYS.map((key) => item(key)), total: 19 };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <SystemConfigPage />
      </App>
    </QueryClientProvider>
  );
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

test("renders the exact catalog with search and no recommendation or consumer status", async () => {
  renderPage();

  expect(
    await screen.findByTestId("config-row-MAX_TENANT_COUNT")
  ).toBeInTheDocument();
  const summary = screen.getByTestId("config-summary");
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(document.querySelector(".ant-card")).toBeInTheDocument();
  expect(document.querySelector(".lucide-database")).toBeInTheDocument();
  expect(screen.getByLabelText("systemConfig.searchLabel")).toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "systemConfig.onlyModified" })
  ).toBeInTheDocument();
  expect(within(summary).getAllByTestId(/^config-summary-/)).toHaveLength(4);
  expect(screen.getByTestId("config-summary-managed")).toHaveTextContent("19");
  expect(screen.getByTestId("config-summary-groups")).toHaveTextContent("4");
  expect(screen.getByTestId("config-summary-modified")).toHaveTextContent("0");
  expect(screen.getByTestId("config-summary-source")).toHaveTextContent(
    "PostgreSQL"
  );
  expect(screen.getByTestId("config-page")).toHaveClass(
    "bg-[var(--color-bg-5)]"
  );
  expect(screen.getByTestId("config-filter")).not.toHaveClass("border");
  expect(screen.getByTestId("config-filter")).not.toHaveClass("shadow-sm");
  expect(screen.getAllByText("systemConfig.hotUpdateTag")).toHaveLength(19);
  expect(
    screen.getAllByText("systemConfig.hotUpdateTag")[0].closest(".ant-tag")
  ).not.toBeNull();
  expect(
    within(screen.getByTestId("config-row-MAX_TENANT_COUNT")).getByRole(
      "button",
      { name: /detail.openFor/ }
    )
  ).toHaveClass("ant-btn-text");
  expect(screen.getAllByTestId(/^config-row-/)).toHaveLength(19);
  expect(screen.queryByText("systemConfig.recommend")).not.toBeInTheDocument();
  expect(
    screen.queryByText("systemConfig.details.open")
  ).not.toBeInTheDocument();
  fireEvent.change(
    screen.getByPlaceholderText("systemConfig.searchPlaceholder"),
    {
      target: { value: "MAX_TENANT_COUNT" },
    }
  );
  expect(screen.getAllByTestId(/^config-row-/)).toHaveLength(1);
});

test("expands real parameter details without revision or consumer status", async () => {
  const baseline = item("MAX_TENANT_COUNT", 90);
  baseline.default_value = 100;
  state.list.mockResolvedValue({ items: [baseline], total: 1 });
  renderPage();

  const row = await screen.findByTestId("config-row-MAX_TENANT_COUNT");
  const toggle = within(row).getByRole("button", {
    name: /systemConfig.detail.openFor/,
  });
  fireEvent.click(toggle);

  const detail = await screen.findByTestId("config-detail-MAX_TENANT_COUNT");
  expect(
    document.querySelector("#config-input-MAX_TENANT_COUNT")
  ).not.toBeNull();
  expect(detail).toHaveTextContent("systemConfig.detail.savedValue");
  expect(detail).toHaveTextContent("systemConfig.detail.defaultValue");
  expect(detail).toHaveTextContent("90");
  expect(detail).toHaveTextContent("100");
  expect(detail).toHaveTextContent("PostgreSQL");
  expect(detail).toHaveTextContent("systemConfig.group.tenant");
  expect(detail).toHaveTextContent("systemConfig.integerType");
  expect(detail).toHaveTextContent("systemConfig.effect.nextRun");
  expect(detail).not.toHaveTextContent("revision");
  expect(detail).not.toHaveTextContent("consumerCount");
  fireEvent.click(toggle);
  expect(
    screen.queryByTestId("config-detail-MAX_TENANT_COUNT")
  ).not.toBeInTheDocument();
});

test("updates the modified summary count as drafts change", async () => {
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  expect(screen.getByTestId("config-summary-modified")).toHaveTextContent("0");
  fireEvent.change(input, { target: { value: "5" } });
  expect(screen.getByTestId("config-summary-modified")).toHaveTextContent("1");
  fireEvent.click(screen.getByRole("button", { name: /discard/ }));
  expect(screen.getByTestId("config-summary-modified")).toHaveTextContent("0");
});

test("places the save bar inside the configuration content container", async () => {
  renderPage();

  const input = await screen.findByLabelText(
    "systemConfig.param.MAX_TENANT_COUNT.label"
  );
  fireEvent.change(input, { target: { value: "5" } });
  const saveButton = screen.getByRole("button", { name: /saveBar.action/ });
  const saveBar = saveButton.parentElement?.parentElement;
  const filter = screen.getByTestId("config-filter");

  expect(saveBar).not.toBeNull();
  expect(saveBar?.parentElement).toBe(filter.parentElement);
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
  fireEvent.click(screen.getByRole("button", { name: /resetDefaultFor/ }));
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
    items: [
      ...KEYS.filter((key) => key !== "MAX_TENANT_COUNT").map((key) =>
        item(key)
      ),
      item("MAX_TENANT_COUNT", 50),
    ],
    total: 19,
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


