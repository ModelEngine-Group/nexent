// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  renderHook,
  waitFor,
  render,
  screen,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "antd";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import { useTrajectoryArchive } from "@/hooks/trajectory/useTrajectoryArchive";
import { trajectoryService } from "@/services/trajectoryService";
import { TrajectoryDrawer } from "@/app/observability/components/TrajectoryDrawer";
import { record, traceNode } from "./trajectoryFixtures";
import type { ImportedTrajectory } from "@/types/trajectory";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: {
    importArchive: vi.fn(),
    conversation: vi.fn(),
    snapshot: vi.fn(),
    content: vi.fn(),
  },
}));
const api = vi.mocked(trajectoryService);
const data: ImportedTrajectory = {
  row: record,
  coverage: { complete: true },
  pages: [
    {
      run: {
        trajectory_id: "local-run",
        round_no: 1,
        turn_no: 1,
        root_agent_id: "7",
        root_agent_version_no: 1,
        root_agent_version_name: null,
        business_status: "completed",
        availability: "available",
        matches_filters: true,
      },
      snapshot: {
        snapshot_id: "",
        conversation_id: record.conversation_id,
        trajectory_id: "local-run",
        root_node_id: "root",
        nodes: [
          traceNode({
            name: "Imported Agent",
            output: {
              availability: "available",
              text: "中文😀完整正文",
              complete: true,
              content_id: null,
            },
          }),
        ],
        context_nodes: [],
        next_cursor: null,
        coverage: { complete: true },
        scope: {
          kind: "execution",
          complete: true,
          aggregates: "execution_subtree",
        },
      },
    },
  ],
};

it("clears on pagehide, allows the same file again and ignores cancelled late results", async () => {
  const file = new File(["zip"], "trace.zip");
  api.importArchive.mockResolvedValue(data);
  const view = renderHook(() => useTrajectoryArchive("account"));
  await act(() => view.result.current.open(file));
  expect(view.result.current.data).toEqual(data);
  act(() => window.dispatchEvent(new Event("pagehide")));
  expect(view.result.current.data).toBeNull();
  let finish!: (value: ImportedTrajectory) => void;
  api.importArchive.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  act(() => {
    void view.result.current.open(file);
  });
  const signal = api.importArchive.mock.calls.at(-1)![1]!;
  act(() => view.result.current.clear());
  expect(signal.aborted).toBe(true);
  await act(async () => finish(data));
  expect(view.result.current.data).toBeNull();
  await act(() => view.result.current.open(file));
  expect(view.result.current.data).toEqual(data);
  view.unmount();
});

it("releases imported data and requests when the account scope changes", async () => {
  api.importArchive.mockResolvedValue(data);
  const view = renderHook(({ scope }) => useTrajectoryArchive(scope), {
    initialProps: { scope: "one" },
  });
  await act(() => view.result.current.open(new File(["zip"], "trace.zip")));
  view.rerender({ scope: "two" });
  expect(view.result.current.data).toBeNull();
  expect(view.result.current.loading).toBe(false);
  view.rerender({ scope: "one" });
  expect(view.result.current.data).toBeNull();
});

it("uses the existing viewer and complete bodies without querying source resources", async () => {
  api.conversation.mockClear();
  api.snapshot.mockClear();
  api.content.mockClear();
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <App>{children}</App>
    </QueryClientProvider>
  );
  const view = render(
    <TrajectoryDrawer row={record} imported={data} onClose={vi.fn()} />,
    { wrapper }
  );
  await waitFor(() =>
    expect(
      screen.getByRole("treeitem", { name: /Imported Agent/ })
    ).toBeVisible()
  );
  expect(screen.getByText(/中文😀完整正文/)).toBeVisible();
  expect(api.conversation).not.toHaveBeenCalled();
  expect(api.snapshot).not.toHaveBeenCalled();
  expect(api.content).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "trajectory.export" })
  ).toBeNull();
  view.unmount();
  expect(
    client
      .getQueryCache()
      .getAll()
      .every((query) => !query.state.data)
  ).toBe(true);
});

it("keeps failed imports empty and recovers without retaining the failed file", async () => {
  api.importArchive.mockRejectedValueOnce({ code: "invalid_archive" });
  const view = renderHook(() => useTrajectoryArchive("account"));
  const file = new File(["zip"], "same.zip");
  await act(() => view.result.current.open(file));
  expect(view.result.current.data).toBeNull();
  expect(view.result.current.error).toEqual({ code: "invalid_archive" });
  expect(view.result.current.loading).toBe(false);
  api.importArchive.mockResolvedValueOnce(data);
  await act(() => view.result.current.open(file));
  expect(view.result.current.data).toEqual(data);
  expect(view.result.current.error).toBeNull();
  act(() => window.dispatchEvent(new Event("auth:logout")));
  expect(view.result.current.data).toBeNull();
});
