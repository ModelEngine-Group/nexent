// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { TrajectoryDrawer } from "@/app/observability/components/TrajectoryDrawer";
import { trajectoryService } from "@/services/trajectoryService";
import { record, traceNode } from "./trajectoryFixtures";
import type { ReactNode } from "react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: {
    conversation: vi.fn(),
    snapshot: vi.fn(),
    content: vi.fn(),
  },
}));
const api = vi.mocked(trajectoryService);
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <App>{children}</App>
    </QueryClientProvider>
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  api.conversation.mockImplementation(async (_row, params) => ({
    snapshot_id: "conversation",
    conversation_id: record.conversation_id,
    executions: [params.cursor ? 2 : 1].map((round_no) => ({
      trajectory_id: `run-${round_no}`,
      round_no,
      turn_no: round_no,
      root_agent_id: "7",
      business_status: round_no === 1 ? "failed" : "completed",
      availability: "available",
      matches_filters: round_no === 1,
      root_agent_version_no: round_no,
      root_agent_version_name: null,
    })),
    next_cursor: params.cursor ? null : "round-2",
    coverage: { complete: true },
    availability: "available",
    active_execution_count: 0,
  }));
  api.snapshot.mockImplementation(async (row) => ({
    snapshot_id: row.trajectory_id!,
    conversation_id: row.conversation_id,
    trajectory_id: row.trajectory_id!,
    root_node_id: "root",
    nodes: [
      traceNode({
        name: row.trajectory_id!,
        status: row.trajectory_id === "run-1" ? "failed" : "completed",
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
  }));
});

it("starts with the first round and appends the next without overwriting duplicate node IDs", async () => {
  render(<TrajectoryDrawer row={record} queryId="query" onClose={vi.fn()} />, {
    wrapper,
  });
  expect(await screen.findByRole("treeitem", { name: /run-1/ })).toBeVisible();
  expect(api.conversation.mock.calls[0][1]).toMatchObject({
    query_id: "query",
  });
  expect(api.snapshot.mock.calls[0][0].trajectory_id).toBe("run-1");
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.loadMore" })
  );
  expect(await screen.findByRole("treeitem", { name: /run-2/ })).toBeVisible();
  expect(screen.getByRole("treeitem", { name: /run-1/ })).toBeVisible();
  await userEvent.click(screen.getByRole("treeitem", { name: /run-1/ }));
  expect(screen.getByRole("heading", { name: "run-1" })).toBeVisible();
  await userEvent.type(
    screen.getByRole("textbox", { name: "trajectory.nodeSearch" }),
    " run-2 "
  );
  expect(
    screen.queryByRole("treeitem", { name: /run-1/ })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("treeitem", { name: /run-2/ })).toBeVisible();
});

it("keeps prior rounds on a transient next-page failure and cancels pending reads on close", async () => {
  api.snapshot.mockRejectedValueOnce(
    Object.assign(new Error(), { code: "query_busy" })
  );
  const view = render(<TrajectoryDrawer row={record} onClose={vi.fn()} />, {
    wrapper,
  });
  expect(await screen.findByText("trajectory.errors.query_busy")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.retry" })
  );
  await screen.findByRole("treeitem", { name: /run-1/ });
  api.snapshot.mockImplementationOnce(() => new Promise(() => {}));
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.loadMore" })
  );
  await waitFor(() => expect(api.snapshot).toHaveBeenCalledTimes(3));
  const signal = api.snapshot.mock.calls.at(-1)![2]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
});

it("keeps earlier readable rounds available when the latest execution was cleaned up", async () => {
  render(
    <TrajectoryDrawer
      row={{ ...record, trajectory_id: null, availability: "expired" }}
      onClose={vi.fn()}
    />,
    { wrapper }
  );
  expect(await screen.findByRole("treeitem", { name: /run-1/ })).toBeVisible();
  expect(api.snapshot.mock.calls[0][0].trajectory_id).toBe("run-1");
});

it("drops loaded nodes on a revoked next segment and refreshes list membership", async () => {
  const reset = vi.fn();
  render(<TrajectoryDrawer row={record} onClose={vi.fn()} onReset={reset} />, {
    wrapper,
  });
  await screen.findByRole("treeitem", { name: /run-1/ });
  api.snapshot.mockRejectedValueOnce(
    Object.assign(new Error(), { code: "snapshot_reset" })
  );
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.loadMore" })
  );
  expect(
    await screen.findByText("trajectory.errors.snapshot_reset")
  ).toBeVisible();
  expect(screen.queryByRole("treeitem")).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.retry" })
  );
  expect(reset).toHaveBeenCalledOnce();
});

it("evicts old segment previews and can reload an earlier round from the same snapshot", async () => {
  api.conversation.mockImplementation(async (_row, params) => {
    const index = params.cursor ? Number(params.cursor) : 1;
    return {
      snapshot_id: "fixed-conversation",
      conversation_id: record.conversation_id,
      executions: [
        {
          trajectory_id: `run-${index}`,
          round_no: index,
          turn_no: index,
          root_agent_id: "7",
          root_agent_version_no: 1,
          root_agent_version_name: null,
          business_status: "completed",
          availability: "available",
          matches_filters: true,
        },
      ],
      next_cursor: index < 5 ? String(index + 1) : null,
      coverage: { complete: true },
      availability: "available",
      active_execution_count: 0,
    };
  });
  render(<TrajectoryDrawer row={record} onClose={vi.fn()} />, { wrapper });
  await screen.findByRole("treeitem", { name: /run-1/ });
  for (let index = 2; index <= 5; index++) {
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.loadMore" })
    );
    await screen.findByRole("treeitem", { name: new RegExp(`run-${index}`) });
  }
  expect(
    screen.queryByRole("treeitem", { name: /run-1/ })
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "trajectory.previousRounds" })
  );
  expect(await screen.findByRole("treeitem", { name: /run-1/ })).toBeVisible();
  expect(api.conversation.mock.calls.at(-1)![1].snapshot_id).toBe(
    "fixed-conversation"
  );
  expect(
    screen.queryByRole("treeitem", { name: /run-5/ })
  ).not.toBeInTheDocument();
});

it("ignores a directory response delivered after the viewer closes", async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.conversation>>) => void;
  api.conversation.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const view = render(<TrajectoryDrawer row={record} onClose={vi.fn()} />, {
    wrapper,
  });
  await waitFor(() => expect(api.conversation).toHaveBeenCalledOnce());
  const signal = api.conversation.mock.calls[0][2]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () =>
    finish({
      snapshot_id: "late",
      conversation_id: record.conversation_id,
      executions: [],
      next_cursor: null,
      coverage: { complete: true },
      availability: "available",
      active_execution_count: 0,
    })
  );
  expect(api.snapshot).not.toHaveBeenCalled();
});
