// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ObservabilityCenter } from "@/app/observability/components/ObservabilityCenter";
import { trajectoryService } from "@/services/trajectoryService";
import type { User } from "@/types/auth";
import { recordsPage } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { records: vi.fn(), facets: vi.fn() },
}));

const api = vi.mocked(trajectoryService);
beforeEach(() => {
  vi.clearAllMocks();
  api.records.mockResolvedValue(recordsPage());
  api.facets.mockResolvedValue({ items: [], next_cursor: null });
});

function center() {
  const user = { id: "owner", tenantId: "tenant", role: "SU" } as User;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ConfigProvider locale={zhCN}>
        <App>
          <ObservabilityCenter user={user} />
        </App>
      </ConfigProvider>
    </QueryClientProvider>
  );
}

describe("trajectory time filter", () => {
  it("confirms a calendar range without changing table sorting", async () => {
    const view = center();
    await waitFor(() =>
      expect(
        view.container.querySelector(".ant-spin-spinning")
      ).not.toBeInTheDocument()
    );
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.filterTime" })
    );
    await userEvent.click(screen.getByPlaceholderText("开始日期"));
    expect(
      await screen.findByRole("button", { name: /确\s*定/ })
    ).toBeDisabled();
    const date = document.querySelector<HTMLElement>(
      ".ant-picker-cell-in-view[title]"
    )!;
    fireEvent.click(date.querySelector(".ant-picker-cell-inner")!);
    const confirm = screen.getByRole("button", { name: /确\s*定/ });
    await waitFor(() => expect(confirm).toBeEnabled());
    await userEvent.click(confirm);
    await userEvent.click(screen.getByPlaceholderText("结束日期"));
    const dates = document.querySelectorAll<HTMLElement>(
      ".ant-picker-cell-in-view[title]"
    );
    const startDate = date.getAttribute("title");
    const endDate = dates[3].getAttribute("title");
    await userEvent.click(dates[3]);
    await userEvent.click(screen.getByRole("button", { name: /确\s*定/ }));
    await waitFor(() =>
      expect(api.records).toHaveBeenLastCalledWith(
        expect.objectContaining({
          started_from: new Date(`${startDate}T00:00:00+08:00`).toISOString(),
          started_to: new Date(`${endDate}T00:00:00+08:00`).toISOString(),
          sort_order: "desc",
        }),
        expect.any(AbortSignal)
      )
    );
    expect(
      view.container.querySelector('th[aria-sort="descending"]')
    ).toHaveTextContent("trajectory.lastExecution");
    expect(
      api.records.mock.calls.every(([params]) => params.sort_order === "desc")
    ).toBe(true);
    await userEvent.click(
      within(document.querySelector<HTMLElement>(".ant-popover")!).getByRole(
        "button",
        {
          name: "trajectory.clear",
        }
      )
    );
    await waitFor(() =>
      expect(api.records.mock.lastCall?.[0].started_from).toBeUndefined()
    );
    expect(api.records.mock.lastCall?.[0].started_to).toBeUndefined();
    await userEvent.click(
      within(view.container).getByRole("columnheader", {
        name: "trajectory.cumulativeDuration",
      })
    );
    await userEvent.click(
      within(view.container).getByRole("columnheader", {
        name: /trajectory.lastExecution/,
      })
    );
    await waitFor(() =>
      expect(api.records.mock.lastCall?.[0]).toMatchObject({
        sort_by: "started_at",
        sort_order: "asc",
      })
    );
  });

  it.each(["开始日期", "结束日期"])(
    "confirms an open range using %s and isolates keyboard events",
    async (placeholder) => {
      const view = center();
      await waitFor(() =>
        expect(
          view.container.querySelector(".ant-spin-spinning")
        ).not.toBeInTheDocument()
      );
      await userEvent.click(
        screen.getByRole("button", { name: "trajectory.filterTime" })
      );
      const input = screen.getByPlaceholderText(placeholder);
      await userEvent.click(input);
      const date = document.querySelector<HTMLElement>(
        ".ant-picker-cell-in-view[title]"
      )!;
      await userEvent.click(date.querySelector(".ant-picker-cell-inner")!);
      await userEvent.click(screen.getByRole("button", { name: /确\s*定/ }));
      fireEvent.keyDown(input, { key: "Enter", keyCode: 13 });
      await userEvent.click(screen.getByRole("heading"));
      const field = placeholder === "开始日期" ? "started_from" : "started_to";
      const empty = placeholder === "开始日期" ? "started_to" : "started_from";
      await waitFor(() =>
        expect(api.records.mock.lastCall?.[0][field]).toEqual(
          expect.any(String)
        )
      );
      expect(api.records.mock.lastCall?.[0][empty]).toBeUndefined();
      expect(
        api.records.mock.calls.every(([params]) => params.sort_order === "desc")
      ).toBe(true);
    }
  );
});
