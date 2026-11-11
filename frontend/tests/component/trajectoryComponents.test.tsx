// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { BodyCache } from "@/lib/trajectory";
import { trajectoryService } from "@/services/trajectoryService";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import ObservabilityPage from "@/app/observability/page";
import { TrajectoryTimeline } from "@/app/observability/components/TrajectoryTimeline";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { TrajectorySummary } from "@/app/observability/components/TrajectorySummary";
import { TrajectoryBody } from "@/app/observability/components/TrajectoryBody";
import { DirectoryFilter } from "@/app/observability/components/DirectoryFilter";
import { TrajectoryDrawer } from "@/app/observability/components/TrajectoryDrawer";
import { ObservabilityCenter } from "@/app/observability/components/ObservabilityCenter";
import { CleanupDialog } from "@/app/observability/components/CleanupDialog";
import { body, record, recordsPage, traceNode } from "./trajectoryFixtures";
import type { AuthorizationContextType } from "@/types/auth";
import { USER_ROLES } from "@/const/auth";
import type { SnapshotPage } from "@/types/trajectory";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: vi.fn(),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: {
    records: vi.fn(),
    facets: vi.fn(),
    snapshot: vi.fn(),
    content: vi.fn(),
    cleanup: vi.fn(),
  },
}));
const api = vi.mocked(trajectoryService);
const auth = vi.mocked(useAuthorizationContext);
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <App>{children}</App>
    </QueryClientProvider>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  api.records.mockResolvedValue(recordsPage());
  api.facets.mockResolvedValue({ items: [], next_cursor: null });
});

describe("observability role gate", () => {
  it.each(["USER", "DEV", "SPEED", "ASSET_OWNER"])(
    "denies %s without fetching protected content",
    (role) => {
      auth.mockReturnValue({
        isAuthzReady: true,
        user: { id: "u", role },
        accessibleRoutes: ["/observability"],
      } as AuthorizationContextType);
      render(<ObservabilityPage />, { wrapper });
      expect(screen.getByText("trajectory.forbidden")).toBeVisible();
      expect(api.records).not.toHaveBeenCalled();
    }
  );
  it("waits for authorization and requires the server menu grant", () => {
    auth.mockReturnValue({
      isAuthzReady: false,
      user: null,
      accessibleRoutes: [],
    } as unknown as AuthorizationContextType);
    const view = render(<ObservabilityPage />, { wrapper });
    expect(api.records).not.toHaveBeenCalled();
    auth.mockReturnValue({
      isAuthzReady: true,
      user: { id: "u", role: "ADMIN" },
      accessibleRoutes: [],
    } as unknown as AuthorizationContextType);
    view.rerender(<ObservabilityPage />);
    expect(screen.getByText("trajectory.forbidden")).toBeVisible();
  });
});

describe("trajectory timeline", () => {
  const root = traceNode();
  const model = traceNode({
    id: "model",
    parent_id: "root",
    name: "DeepSeek",
    kind: "model",
  });
  const tool = traceNode({
    id: "tool",
    parent_id: "model",
    name: "SearchTool",
    kind: "tool",
    output: body("retention_days"),
  });
  it("collapses descendants with one toggle, then search retains the ancestor path", async () => {
    const user = userEvent.setup();
    render(
      <TrajectoryTimeline
        nodes={[root, model, tool]}
        root={root}
        complete
        cache={new BodyCache()}
        onSelect={vi.fn()}
      />
    );
    await user.click(
      screen.getByRole("button", { name: "trajectory.collapseAll" })
    );
    expect(
      screen.queryByRole("treeitem", { name: /DeepSeek/ })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "trajectory.expandAll" })
    ).toBeVisible();
    await user.type(
      screen.getByRole("textbox", { name: "trajectory.nodeSearch" }),
      "retention_days"
    );
    expect(screen.getByRole("treeitem", { name: /SearchTool/ })).toBeVisible();
    expect(screen.getByRole("treeitem", { name: /Root Agent/ })).toBeVisible();
  });
  it("keeps parallel spans on the shared root time scale", () => {
    const a = traceNode({
      id: "a",
      parent_id: "root",
      started_at: "2026-11-10T01:00:00.500Z",
      duration_ms: 500,
    });
    const b = traceNode({
      id: "b",
      parent_id: "root",
      started_at: a.started_at,
      duration_ms: 1000,
    });
    const view = render(
      <TrajectoryTimeline
        nodes={[root, a, b]}
        root={root}
        complete
        cache={new BodyCache()}
        onSelect={vi.fn()}
      />
    );
    const bars = view.container.querySelectorAll(".trajectory-time-bar");
    expect(bars[1]).toHaveStyle({ left: "25%", width: "25%" });
    expect(bars[2]).toHaveStyle({ left: "25%", width: "50%" });
    expect(
      view.container.querySelectorAll(".trajectory-range-guide")
    ).toHaveLength(2);
  });
});

describe("node details and bounded body reads", () => {
  it.each(["agent", "tool"])(
    "does not show model-only metrics on %s",
    (kind) => {
      render(
        <TrajectoryNodeDetail
          node={traceNode({ kind })}
          conversationId="1"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />,
        { wrapper }
      );
      expect(screen.queryByText("trajectory.ttft")).not.toBeInTheDocument();
      expect(
        screen.queryByText("trajectory.throughput")
      ).not.toBeInTheDocument();
      expect(screen.getByText(/trajectory.finished/)).toHaveTextContent(
        "2026-11-10 09:00:02"
      );
    }
  );
  it("shows valid model zero TTFT and unknown throughput separately", () => {
    render(
      <TrajectoryNodeDetail
        node={traceNode({ kind: "model", ttft_ms: 0, throughput: null })}
        conversationId="1"
        cache={new BodyCache()}
        onParent={vi.fn()}
        onLoaded={vi.fn()}
      />,
      { wrapper }
    );
    expect(screen.getByText("0 ms")).toBeVisible();
    expect(screen.getByText("— Token/s")).toBeVisible();
    expect(screen.queryByText("trajectory.modelCalls")).not.toBeInTheDocument();
  });
  it("uses returned UTF-8 byte offset, replaces chunks, and aborts on unmount", async () => {
    const user = userEvent.setup();
    api.content.mockResolvedValueOnce({
      text: "中文",
      offset: 0,
      next_offset: 6,
      complete: false,
      byte_count: 12,
      char_count: 4,
      offset_unit: "utf8_bytes",
    });
    let resolve!: (value: Awaited<ReturnType<typeof api.content>>) => void;
    api.content.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const cache = new BodyCache();
    const view = render(
      <TrajectoryBody
        reference={body("预览", false)}
        slot="input"
        conversationId="1"
        nodeId="n"
        cache={cache}
        onLoaded={vi.fn()}
      />,
      { wrapper }
    );
    await user.click(
      screen.getByRole("button", { name: "trajectory.expandContent" })
    );
    expect(await screen.findByText("中文")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "trajectory.nextChunk" })
    );
    expect(api.content.mock.calls[1][2]).toBe(6);
    const signal = api.content.mock.calls[1][3]!;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () =>
      resolve({
        text: "后续",
        offset: 6,
        next_offset: 12,
        complete: true,
        byte_count: 12,
        char_count: 4,
        offset_unit: "utf8_bytes",
      })
    );
    expect(cache.bytes).toBeLessThanOrEqual(32 * 1024 * 1024);
  });
  it("reports missing reasoning without invoking a model", () => {
    render(
      <TrajectoryBody
        reference={{ ...body(), availability: "not_returned", text: null }}
        slot="reasoning"
        conversationId="1"
        nodeId="n"
        cache={new BodyCache()}
        onLoaded={vi.fn()}
      />,
      { wrapper }
    );
    expect(
      screen.getByText("trajectory.bodyAvailability.not_returned")
    ).toBeVisible();
    expect(api.content).not.toHaveBeenCalled();
  });
});

describe("summary, facets and drawer", () => {
  it("does not invent zero samples before a complete server summary exists", () => {
    render(<TrajectorySummary />);
    expect(screen.getAllByText("trajectory.samplesUnknown")).toHaveLength(3);
  });
  it("uses server summary rather than rows on the current page", () => {
    const { summary } = recordsPage();
    render(<TrajectorySummary summary={summary} />);
    expect(screen.getByText("30")).toBeVisible();
    expect(screen.getByText("3")).toBeVisible();
  });
  it("debounces remote option search and supports loading the next page", async () => {
    api.facets
      .mockResolvedValueOnce({
        items: [{ id: "1", name: "Owner", tenant_id: "t" }],
        next_cursor: "more",
      })
      .mockResolvedValue({ items: [], next_cursor: null });
    const onChange = vi.fn();
    render(
      <DirectoryFilter
        facet="users"
        filters={{ tenant_id: "t" }}
        onChange={onChange}
      />,
      { wrapper }
    );
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("Owner")).toBeVisible());
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.loadMore" })
    );
    await waitFor(() =>
      expect(api.facets.mock.calls.some((call) => call[3] === "more")).toBe(
        true
      )
    );
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "Other" },
    });
    expect(
      api.facets.mock.calls.filter((call) => call[2] === "Other")
    ).toHaveLength(0);
    await waitFor(() =>
      expect(api.facets.mock.calls.some((call) => call[2] === "Other")).toBe(
        true
      )
    );
  });
  it("fetches a specific execution, closes via mask, and aborts pending segment on unmount", async () => {
    api.snapshot.mockResolvedValue({
      snapshot_id: "snap",
      conversation_id: record.conversation_id,
      trajectory_id: "execution",
      root_node_id: "root",
      nodes: [traceNode()],
      context_nodes: [],
      next_cursor: "next",
      coverage: { complete: true },
      scope: {
        kind: "execution",
        complete: false,
        aggregates: "execution_subtree",
      },
    });
    const close = vi.fn();
    const view = render(<TrajectoryDrawer row={record} onClose={close} />, {
      wrapper,
    });
    expect(await screen.findByRole("treeitem")).toBeVisible();
    expect(api.snapshot.mock.calls[0][0].trajectory_id).toBe("execution");
    fireEvent.click(document.querySelector(".ant-drawer-mask")!);
    expect(close).toHaveBeenCalledOnce();
    api.snapshot.mockImplementationOnce(
      () => new Promise<SnapshotPage>(() => {})
    );
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.nextSegment" })
    );
    await waitFor(() => expect(api.snapshot).toHaveBeenCalledTimes(2));
    expect(api.snapshot.mock.calls[1][1]).toEqual({
      cursor: "next",
      snapshot_id: "snap",
    });
    const signal = api.snapshot.mock.calls[1][2]!;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });
  it("never requests a snapshot for an expired placeholder row", () => {
    render(
      <TrajectoryDrawer
        row={{ ...record, trajectory_id: null, availability: "expired" }}
        onClose={vi.fn()}
      />,
      { wrapper }
    );
    expect(screen.getByText("trajectory.availability.expired")).toBeVisible();
    expect(api.snapshot).not.toHaveBeenCalled();
  });
  it("drops the viewer and cached bodies when a content reference is invalidated", async () => {
    api.snapshot.mockResolvedValue({
      snapshot_id: "snap",
      conversation_id: record.conversation_id,
      trajectory_id: "execution",
      root_node_id: "root",
      nodes: [traceNode({ input: body("private preview", false) })],
      context_nodes: [],
      next_cursor: null,
      coverage: { complete: true },
      scope: {
        kind: "execution",
        complete: true,
        aggregates: "execution_subtree",
      },
    });
    api.content.mockRejectedValueOnce(
      Object.assign(new Error(), { code: "snapshot_reset" })
    );
    render(<TrajectoryDrawer row={record} onClose={vi.fn()} />, { wrapper });
    await screen.findByText("private preview");
    await userEvent.click(
      screen.getAllByRole("button", { name: "trajectory.expandContent" })[0]
    );
    await waitFor(() =>
      expect(screen.queryByText("private preview")).not.toBeInTheDocument()
    );
    expect(screen.getByText("trajectory.errors.snapshot_reset")).toBeVisible();
    expect(screen.queryByRole("treeitem")).not.toBeInTheDocument();
  });
});

describe("administrator page and cleanup confirmation", () => {
  const admin = {
    id: "admin",
    email: "admin@example.test",
    role: USER_ROLES.ADMIN,
    tenantId: "tenant",
  };
  it("opens with the authenticated tenant and queries on explicit ID submit", async () => {
    render(<ObservabilityCenter user={admin} />, { wrapper });
    await waitFor(() => expect(api.records).toHaveBeenCalledOnce());
    expect(api.records.mock.calls[0][0]).toMatchObject({
      tenant_id: "tenant",
      page: 1,
      page_size: 10,
    });
    await userEvent.type(
      screen.getByRole("textbox", { name: "trajectory.idSearch" }),
      "9223372036854775806"
    );
    expect(api.records).toHaveBeenCalledOnce();
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.query" })
    );
    await waitFor(() => expect(api.records).toHaveBeenCalledTimes(2));
    expect(api.records.mock.calls[1][0].id_query).toBe("9223372036854775806");
    expect(api.records.mock.calls[1][0].query_id).toBeUndefined();
  });
  it("clears lower selectors and pending keyword when a user changes", async () => {
    api.facets.mockImplementation(async (facet) => ({
      items: [
        {
          id: facet === "users" ? "new-owner" : "12",
          name: facet === "users" ? "New Owner" : "Historical Agent",
          tenant_id: "tenant",
        },
      ],
      next_cursor: null,
    }));
    render(<ObservabilityCenter user={admin} />, { wrapper });
    await userEvent.type(
      screen.getByRole("textbox", { name: "trajectory.idSearch" }),
      "old draft"
    );
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "trajectory.users" })
    );
    await waitFor(() => expect(screen.getByText("New Owner")).toBeVisible());
    await userEvent.click(screen.getByText("New Owner"));
    await waitFor(() =>
      expect(api.records.mock.calls.at(-1)?.[0].target_user_id).toBe(
        "new-owner"
      )
    );
    expect(
      screen.getByRole("textbox", { name: "trajectory.idSearch" })
    ).toHaveValue("");
    expect(api.records.mock.calls.at(-1)?.[0].conversation_id).toBeUndefined();
  });
  it("does not enable cross-tenant cleanup just because SU can list tenants", async () => {
    render(<ObservabilityCenter user={{ ...admin, role: USER_ROLES.SU }} />, {
      wrapper,
    });
    expect(
      screen.getByRole("button", { name: "trajectory.cleanup" })
    ).toBeDisabled();
  });
  it("requires confirmation, validates days and shows partial batch completion", async () => {
    api.cleanup.mockResolvedValue({
      cutoff_at: "2026-11-03T01:00:00Z",
      scanned_runs: 5,
      deleted_runs: 3,
      deleted_bytes: 400,
      skipped_active: 1,
      pending_runs: 1,
      failed_runs: 1,
      done: true,
      next_cursor: null,
    });
    const complete = vi.fn();
    render(
      <CleanupDialog tenant="tenant" onClose={vi.fn()} onComplete={complete} />,
      { wrapper }
    );
    expect(api.cleanup).not.toHaveBeenCalled();
    const days = screen.getByRole("spinbutton", {
      name: "trajectory.beforeDays",
    });
    await userEvent.clear(days);
    expect(
      screen.getByRole("button", { name: "trajectory.confirmCleanup" })
    ).toBeDisabled();
    await userEvent.type(days, "7");
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.confirmCleanup" })
    );
    expect(await screen.findByText("trajectory.cleanupPartial")).toBeVisible();
    expect(
      screen.queryByText("trajectory.cleanupDone")
    ).not.toBeInTheDocument();
    expect(api.cleanup.mock.calls[0][0]).toBe(7);
    expect(complete).toHaveBeenCalledOnce();
  });
});
