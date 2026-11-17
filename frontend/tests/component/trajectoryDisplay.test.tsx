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
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import type { PaginationProps } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DirectoryFilter } from "@/app/observability/components/DirectoryFilter";
import { TrajectoryBody } from "@/app/observability/components/TrajectoryBody";
import { ObservabilityCenter } from "@/app/observability/components/ObservabilityCenter";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { userInputPreview } from "@/app/observability/components/TrajectoryPresentation";
import { TrajectoryTimeline } from "@/app/observability/components/TrajectoryTimeline";
import { BodyCache } from "@/lib/trajectory";
import * as trajectoryUtils from "@/lib/trajectory";
import { getTenant } from "@/services/tenantService";
import { trajectoryService } from "@/services/trajectoryService";
import type { User } from "@/types/auth";
import { body, record, recordsPage, traceNode } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/tenantService", () => ({ getTenant: vi.fn() }));
// Exercise center-owned page transitions independently of AntD layout effects.
vi.mock("antd", async (importOriginal) => ({
  ...(await importOriginal<typeof import("antd")>()),
  Pagination: ({ current = 1, pageSize = 10, onChange }: PaginationProps) => (
    <button
      aria-label="test.nextPage"
      onClick={() => onChange?.(current + 1, pageSize)}
    >
      {current}
    </button>
  ),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: {
    records: vi.fn(),
    facets: vi.fn(),
  },
}));

const api = vi.mocked(trajectoryService);
const tenant = vi.mocked(getTenant);
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <App>{children}</App>
    </QueryClientProvider>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  api.records.mockReset();
  api.records.mockResolvedValue(recordsPage());
  api.facets.mockResolvedValue({ items: [], next_cursor: null });
  tenant.mockResolvedValue({ tenant_id: "tenant", tenant_name: "示例租户" });
});

describe("round user input display", () => {
  it.each([
    ["查询天气", "查询天气"],
    [
      JSON.stringify({
        query: "查询天气",
        effective_config: { name: "internal" },
      }),
      "查询天气",
    ],
    ['{"query":"查询天气","effective_config":{', "查询天气"],
    ['{"query":"查询天', ""],
    ['{"effective_config":{"name":"internal"', ""],
    [JSON.stringify({ effective_config: { name: "internal" } }), ""],
    [JSON.stringify({ query: { text: "查询天气" } }), "查询天气"],
    [
      JSON.stringify({
        messages: [
          { role: "user", content: "之前的问题" },
          { role: "assistant", content: "回复" },
          { role: "user", content: "查询天气" },
        ],
      }),
      "查询天气",
    ],
    [null, ""],
  ])("extracts user text from %s", (input, expected) => {
    expect(userInputPreview(input)).toBe(expected);
  });

  it("renders only the user query in the round heading and tooltip", () => {
    const node = traceNode({
      round_no: 1,
      input: body(
        JSON.stringify({
          query: "查询天气",
          effective_config: { name: "internal" },
        })
      ),
    });
    const view = render(
      <TrajectoryTimeline
        nodes={[node]}
        complete
        cache={new BodyCache()}
        onSelect={vi.fn()}
      />
    );
    const heading = view.container.querySelector(".trajectory-round-heading")!;
    expect(heading).toHaveTextContent("查询天气");
    expect(heading).not.toHaveTextContent("effective_config");
    expect(within(heading as HTMLElement).getByTitle("查询天气")).toBeVisible();
  });
});

describe("directory names", () => {
  it.each(["tenants", "users", "agents", "conversations"] as const)(
    "shows names without IDs in %s candidates and selection",
    async (facet) => {
      api.facets.mockResolvedValue({
        items: [
          {
            id: "internal-id",
            name: "展示名称",
            tenant_id: "tenant",
            tenant_name: "示例租户",
          },
        ],
        next_cursor: null,
      });
      const onChange = vi.fn();
      const view = render(
        <DirectoryFilter facet={facet} filters={{}} onChange={onChange} />,
        { wrapper }
      );
      fireEvent.mouseDown(screen.getByRole("combobox"));
      const candidate = await screen.findByText("展示名称");
      if (facet === "users") {
        expect(screen.queryByText("示例租户")).not.toBeInTheDocument();
      } else {
        expect(screen.getByText("示例租户")).toBeInTheDocument();
      }
      await userEvent.click(candidate);
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ id: "internal-id" })
      );
      view.rerender(
        <DirectoryFilter
          facet={facet}
          filters={{}}
          value="internal-id"
          onChange={onChange}
        />
      );
      expect(within(view.container).getByTitle("展示名称")).toBeVisible();
      expect(
        within(view.container).queryByText("示例租户")
      ).not.toBeInTheDocument();
      expect(screen.queryByText("internal-id")).not.toBeInTheDocument();
    }
  );

  it("does not display an ID supplied as the fallback name", async () => {
    api.facets.mockResolvedValue({
      items: [
        {
          id: "internal-id",
          name: "internal-id",
          tenant_id: "tenant",
          tenant_name: "tenant",
        },
      ],
      next_cursor: null,
    });
    render(<DirectoryFilter facet="agents" filters={{}} onChange={vi.fn()} />, {
      wrapper,
    });
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(screen.getByText("trajectory.unnamedOption")).toBeVisible()
    );
    expect(screen.queryByText("internal-id")).not.toBeInTheDocument();
    expect(screen.queryByText("tenant")).not.toBeInTheDocument();
  });
});

describe("trajectory body default format", () => {
  it.each(["input", "reasoning", "output"])(
    "formats %s as JSON by default and allows switching to text",
    async (slot) => {
      const text = '{"content":"示例内容","items":[1,2]}';
      const view = render(
        <TrajectoryBody
          reference={body(text)}
          slot={slot}
          conversationId="1"
          nodeId="node"
          cache={new BodyCache()}
          onLoaded={vi.fn()}
        />,
        { wrapper }
      );
      expect(screen.getByRole("radio", { name: "JSON" })).toBeChecked();
      expect(view.container.querySelector("pre code")?.textContent).toBe(
        JSON.stringify(JSON.parse(text), null, 2)
      );
      await userEvent.click(screen.getByText("trajectory.text"));
      expect(view.container.querySelector("pre code")?.textContent).toBe(text);
    }
  );
});

describe("documented execution information", () => {
  it.each(["agent", "model", "tool"])(
    "shows only documented fields for a %s node",
    (kind) => {
      const node = traceNode({
        kind,
        model: "Example model",
        agent_version_no: 2,
        agent_version_name: "Published version",
        attributes: {
          "llm.ttft_basis": "reasoning",
          "nexent.attempt_id": "internal-attempt",
          "nexent.attempt_no": 1,
          "nexent.invocation_id": "internal-invocation",
          "future.attribute": { detail: "internal detail" },
        },
      });
      const view = render(
        <TrajectoryNodeDetail
          node={node}
          conversationId="1"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />,
        { wrapper }
      );
      const info = view.container.querySelector(".trajectory-info")!;
      expect(
        [...info.querySelectorAll("dt")].map((term) => term.textContent)
      ).toEqual([
        "trajectory.users",
        ...(kind === "agent"
          ? ["trajectory.agentVersion", "trajectory.versionName"]
          : []),
        "trajectory.models",
        "TraceID",
        "trajectory.directCalls",
      ]);
      expect(info).toHaveTextContent("Owner");
      expect(info).toHaveTextContent("Example model");
      expect(info).toHaveTextContent(node.display_trace_id);
      for (const key of Object.keys(node.attributes)) {
        expect(screen.queryByText(key)).not.toBeInTheDocument();
      }
      expect(screen.queryByText("internal-attempt")).not.toBeInTheDocument();
      expect(screen.queryByText("internal-invocation")).not.toBeInTheDocument();
    }
  );
});

describe("admin list display", () => {
  it.each([false, true])(
    "keeps cleaned metrics visible and reports only actual missing usage (%s)",
    async (missing) => {
      const page = recordsPage();
      page.items = [
        {
          ...record,
          root_agent_name: "cleaned-agent",
          status: null,
          availability: "expired",
          duration_ms: 1250,
          usage: {
            input: 10,
            output: missing ? null : 20,
            total: missing ? null : 30,
            complete: !missing,
          },
        },
      ];
      api.records.mockResolvedValue(page);
      render(
        <ObservabilityCenter
          user={{ id: "operator", role: "OPS", tenantId: "tenant" } as User}
        />,
        { wrapper }
      );
      const agent = await screen.findByRole("button", {
        name: "cleaned-agent",
      });
      const row = within(agent.closest("tr")!);
      expect(row.getByText("trajectory.availability.expired")).toBeVisible();
      expect(row.getByText("1.25 s")).toBeVisible();
      if (missing) expect(row.getByText("trajectory.partial")).toBeVisible();
      else {
        expect(row.getByText("30")).toBeVisible();
        expect(row.queryByText("trajectory.partial")).not.toBeInTheDocument();
      }
    }
  );

  it.each([
    ["cancelled", "trajectory.businessStatus.cancelled"],
    ["unarchived", "trajectory.availability.unarchived"],
  ])(
    "shows %s and submits the matching status filter",
    async (status, label) => {
      const page = recordsPage();
      page.items = [
        {
          ...record,
          root_agent_name: `${status}-agent`,
          status: status === "cancelled" ? "cancelled" : null,
          availability: status === "unarchived" ? "unarchived" : "available",
        },
      ];
      api.records.mockResolvedValue(page);
      render(
        <ObservabilityCenter
          user={{ id: "operator", role: "OPS", tenantId: "tenant" } as User}
        />,
        { wrapper }
      );
      expect(await screen.findByText(label)).toBeVisible();
      expect(screen.queryByText("trajectory.error")).not.toBeInTheDocument();
      const header = screen.getByRole("columnheader", {
        name: /trajectory.status/,
      });
      await userEvent.click(within(header).getByRole("button"));
      await userEvent.click(
        await screen.findByRole("menuitem", {
          name: label,
        })
      );
      await userEvent.click(screen.getByRole("button", { name: "OK" }));
      await waitFor(() =>
        expect(api.records.mock.calls.at(-1)?.[0].status).toBe(status)
      );
    }
  );

  it.each([
    ["OPS", ["OPS"], "OPS"],
    ["SU", ["SU"], "SU"],
    ["ADMIN", ["ADMIN", "OPS"], "OPS"],
    ["DEV", ["DEV", "OPS"], "OPS"],
  ] as const)(
    "renders the %s tenant layout with roles %j",
    async (role, roles, layoutRole) => {
      const page = recordsPage();
      page.summary.coverage = { complete: false };
      page.items = [
        {
          ...record,
          root_agent_name: "通用智能体",
          coverage: { complete: false },
        },
      ];
      api.records.mockResolvedValue(page);
      const view = render(
        <ObservabilityCenter
          user={
            { id: "admin", role, roles: [...roles], tenantId: "tenant" } as User
          }
        />,
        { wrapper }
      );
      expect(
        await screen.findByRole("button", { name: "通用智能体" })
      ).toBeVisible();
      expect(
        view.container.querySelector(".trajectory-filters")
      ).toHaveAttribute("data-role", layoutRole);
      if (layoutRole === "OPS") {
        expect(screen.queryByText("示例租户")).not.toBeInTheDocument();
        expect(tenant).not.toHaveBeenCalled();
        expect(
          screen.queryByRole("combobox", { name: "trajectory.tenants" })
        ).not.toBeInTheDocument();
        expect(
          screen.queryByRole("columnheader", { name: "trajectory.tenants" })
        ).not.toBeInTheDocument();
        expect(
          view.container.querySelector(".trajectory-fixed-tenant")
        ).toBeNull();
      } else {
        expect(
          screen.getByRole("columnheader", { name: "trajectory.tenants" })
        ).toBeVisible();
        expect(tenant).not.toHaveBeenCalled();
      }
      expect(view.container.querySelector(".trajectory-role")).toBeNull();
      expect(
        view.container.querySelector(".trajectory-conversation-count small")
      ).toBeNull();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByText("trajectory.partial")).not.toBeInTheDocument();
      expect(
        screen.queryByText("trajectory.retention")
      ).not.toBeInTheDocument();
    }
  );

  it("keeps tenant scoping after clearing filters without displaying its name", async () => {
    render(
      <ObservabilityCenter
        user={{ id: "admin", role: "OPS", tenantId: "tenant" } as User}
      />,
      { wrapper }
    );
    expect(
      await screen.findByRole("button", { name: "Root Agent" })
    ).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.clear" })
    );
    expect(api.records.mock.calls.at(-1)?.[0].tenant_id).toBe("tenant");
    expect(screen.queryByText("Tenant")).not.toBeInTheDocument();
    expect(tenant).not.toHaveBeenCalled();
  });
});

describe("trajectory page refresh", () => {
  it("refreshes records and summary while retaining filters and sorting and returning to page one", async () => {
    const view = render(
      <ObservabilityCenter
        user={{ id: "admin", role: "OPS", tenantId: "tenant" } as User}
      />,
      { wrapper }
    );
    await screen.findByRole("button", { name: "Root Agent" });
    await userEvent.type(
      screen.getByRole("textbox", { name: "trajectory.idSearch" }),
      " 42 {enter}"
    );
    await waitFor(() =>
      expect(api.records.mock.calls.at(-1)?.[0].id_query).toBe("42")
    );
    fireEvent.click(screen.getAllByText("trajectory.cumulativeDuration")[0]);
    await waitFor(() =>
      expect(api.records.mock.calls.at(-1)?.[0].sort_by).toBe("duration_ms")
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "common.refresh" })
      ).not.toBeDisabled()
    );
    await userEvent.click(
      screen.getByRole("button", { name: "test.nextPage" })
    );
    await waitFor(() =>
      expect(api.records.mock.calls.at(-1)?.[0]).toMatchObject({
        page: 2,
        query_id: "signed-query",
      })
    );
    const next = recordsPage("refreshed-query");
    next.items = [{ ...record, root_agent_name: "Refreshed Agent" }];
    next.summary.conversation_count = 31;
    api.records.mockResolvedValueOnce(next);
    await userEvent.click(
      screen.getByRole("button", { name: "common.refresh" })
    );
    expect(
      await screen.findByRole("button", { name: "Refreshed Agent" })
    ).toBeVisible();
    expect(api.records.mock.calls.at(-1)?.[0]).toMatchObject({
      tenant_id: "tenant",
      id_query: "42",
      sort_by: "duration_ms",
      sort_order: "asc",
      page: 1,
      query_id: undefined,
    });
    expect(
      screen.getByRole("textbox", { name: "trajectory.idSearch" })
    ).toHaveValue(" 42 ");
    expect(
      view.container.querySelector(".trajectory-summary")
    ).toHaveTextContent("31");
    expect(
      screen.getByRole("button", { name: "test.nextPage" })
    ).toHaveTextContent("1");
  });

  it("prevents duplicate refresh requests and allows retry after a failed refresh", async () => {
    render(
      <ObservabilityCenter
        user={{ id: "admin", role: "OPS", tenantId: "tenant" } as User}
      />,
      { wrapper }
    );
    await screen.findByRole(
      "button",
      { name: "Root Agent" },
      { timeout: 5000 }
    );
    let fail!: (error: Error) => void;
    api.records.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          fail = reject;
        })
    );
    const refresh = screen.getByRole("button", { name: "common.refresh" });
    await userEvent.click(refresh);
    await waitFor(() => expect(api.records).toHaveBeenCalledTimes(2));
    expect(refresh).toBeDisabled();
    fireEvent.click(refresh);
    expect(api.records).toHaveBeenCalledTimes(2);
    await act(async () => fail(new Error("unavailable")));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(refresh).not.toBeDisabled();
    await userEvent.click(refresh);
    expect(
      await screen.findByRole(
        "button",
        { name: "Root Agent" },
        { timeout: 5000 }
      )
    ).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.records).toHaveBeenCalledTimes(3);
    expect(api.records.mock.calls.at(-1)?.[0]).toMatchObject({
      tenant_id: "tenant",
      query_id: undefined,
    });
  });
});

describe("whole-scope statistics", () => {
  it("shows scope and the original computation time", async () => {
    const { TrajectorySummary } =
      await import("@/app/observability/components/TrajectorySummary");
    const summary = {
      ...recordsPage().summary,
      scope_type: "tenant" as const,
      scope_id: "private-tenant-id",
      computed_at: "2026-11-13T00:00:00Z",
      source_revision: 8,
      computed_revision: 7,
    };
    render(<TrajectorySummary summary={summary} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "trajectory.statisticsTenant"
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "trajectory.statisticsComputedAt"
    );
    expect(screen.queryByText("private-tenant-id")).not.toBeInTheDocument();
  });

  it("shows preparing before the first complete snapshot", async () => {
    const { TrajectorySummary } =
      await import("@/app/observability/components/TrajectorySummary");
    render(
      <TrajectorySummary
        summary={{
          ...recordsPage().summary,
          complete: false,
          scope_type: "global",
          computed_at: null,
        }}
      />
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "trajectory.statisticsPreparing"
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "trajectory.statisticsGlobal"
    );
  });
});

describe("trajectory tree selection cost", () => {
  it("keeps the derived tree when selecting a different node", () => {
    const filter = vi.spyOn(trajectoryUtils, "filterTree");
    const nodes = [
      traceNode(),
      traceNode({ id: "child", parent_id: "node", kind: "tool" }),
    ];
    const props = {
      nodes,
      complete: true,
      cache: new BodyCache(),
      onSelect: vi.fn(),
    };
    const view = render(
      <TrajectoryTimeline {...props} selected={nodes[0].id} />
    );
    const before = filter.mock.calls.length;
    expect(before).toBeGreaterThan(0);
    view.rerender(<TrajectoryTimeline {...props} selected="child" />);
    expect(filter).toHaveBeenCalledTimes(before);
    expect(screen.getByRole("treeitem", { selected: true })).toBeVisible();
    filter.mockRestore();
  });
});
