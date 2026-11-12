// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DirectoryFilter } from "@/app/observability/components/DirectoryFilter";
import { TrajectoryBody } from "@/app/observability/components/TrajectoryBody";
import { ObservabilityCenter } from "@/app/observability/components/ObservabilityCenter";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { userInputPreview } from "@/app/observability/components/TrajectoryPresentation";
import { TrajectoryTimeline } from "@/app/observability/components/TrajectoryTimeline";
import { BodyCache } from "@/lib/trajectory";
import { getTenant } from "@/services/tenantService";
import { trajectoryService } from "@/services/trajectoryService";
import type { User } from "@/types/auth";
import { body, record, recordsPage, traceNode } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/tenantService", () => ({ getTenant: vi.fn() }));
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
      await userEvent.click(await screen.findByText("展示名称"));
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
  it.each(["ADMIN", "SU"] as const)(
    "renders the %s tenant layout",
    async (role) => {
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
          user={{ id: "admin", role, tenantId: "tenant" } as User}
        />,
        { wrapper }
      );
      expect(
        await screen.findByRole("button", { name: "通用智能体" })
      ).toBeVisible();
      if (role === "ADMIN") {
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
    }
  );

  it("keeps tenant scoping after clearing filters without displaying its name", async () => {
    render(
      <ObservabilityCenter
        user={{ id: "admin", role: "ADMIN", tenantId: "tenant" } as User}
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
