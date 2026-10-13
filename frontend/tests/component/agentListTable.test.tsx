import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AgentListTable, {
  formatAgentUpdateTime,
} from "../../app/[locale]/agents/components/agent-list-table";
import type { Agent } from "@/types/agentConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        "agentConfig.list.column.name": "名称",
        "agentConfig.list.column.type": "类型",
        "agentConfig.list.column.description": "描述",
        "agentConfig.list.column.status": "状态",
        "agentConfig.list.column.creator": "创建人",
        "agentConfig.list.column.updatedAt": "更新时间",
        "agentConfig.list.column.actions": "操作",
        "agentConfig.list.online": "已上线",
        "agentConfig.list.offline": "未上线",
        "agentConfig.list.configure": "配置",
        "agentConfig.list.publish": "发布",
      };
      return translations[key] ?? key;
    },
  }),
}));

vi.mock("../../app/[locale]/agents/components/agent-config-actions", () => ({
  default: () => <button type="button">更多</button>,
}));

const firstAgent = {
  id: "1",
  name: "health_agent",
  display_name: "健康小助手",
  description: "提供可靠、实用的健康信息。",
  tags: ["保健"],
  author: "刘晨",
  create_time: "2026-09-17T10:30:00",
  update_time: "2026-09-18T10:30:00",
  current_version_no: 2,
  permission: "EDIT",
} as Agent;

const secondAgent = {
  ...firstAgent,
  id: "2",
  name: "research_agent",
  display_name: "资料助手",
  author: undefined,
  update_time: undefined,
  current_version_no: undefined,
} as Agent;

describe("AgentListTable", () => {
  it("renders the specified columns and uses only update_time for the date", () => {
    const { getByTestId } = render(
      <AgentListTable
        agents={[firstAgent, secondAgent]}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );

    expect(
      screen.getAllByRole("columnheader").map((header) => header.textContent)
    ).toEqual(["名称", "类型", "描述", "状态", "创建人", "更新时间", "操作"]);
    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(table.closest(".nexent-standard-table")).toBeInTheDocument();

    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("刘晨")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2026-09-18")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("2026-09-17")).not.toBeInTheDocument();
    expect(within(rows[1]).getAllByText("-")).toHaveLength(2);
    expect(getByTestId("agent-list-table-scroll")).toHaveClass(
      "h-auto",
      "max-h-[500px]",
      "overflow-auto"
    );
    expect(getByTestId("agent-list-table-scroll")).not.toHaveClass("flex-1");
    expect(table.closest(".nexent-standard-table")?.className).toContain(
      "[&_.ant-table-thead>tr>th:not(:last-child):not([colspan])::before]:!h-[14px]"
    );
    expect(table.closest(".nexent-standard-table")?.className).toContain(
      "[&_.ant-table-thead>tr>th:not(:last-child):not([colspan])::before]:!bg-[#c9c9c9]"
    );
    expect(table.closest(".nexent-standard-table")?.className).toContain(
      "[&_.ant-table-thead>tr>th:not(:last-child):not([colspan])::before]:![transform:translateY(-50%)]"
    );
    expect(table.closest(".nexent-standard-table")?.className).not.toContain(
      "-translate-y-1/2"
    );
  });

  it("keeps row detail, configure, and publish actions connected", () => {
    const onOpen = vi.fn();
    const onConfigure = vi.fn();
    const onPublish = vi.fn();
    render(
      <AgentListTable
        agents={[firstAgent, secondAgent]}
        onOpen={onOpen}
        onConfigure={onConfigure}
        onPublish={onPublish}
        onManageVersions={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "健康小助手" }));
    fireEvent.click(screen.getAllByRole("button", { name: "配置" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "发布" })[0]);
    expect(onOpen).toHaveBeenCalledWith(firstAgent);
    expect(onConfigure).toHaveBeenCalledWith(1);
    expect(onPublish).toHaveBeenCalledWith(2);
  });

  it("formats only valid update timestamps", () => {
    expect(formatAgentUpdateTime("2026-09-18T10:30:00")).toBe("2026-09-18");
    expect(formatAgentUpdateTime("2026-02-30T10:30:00")).toBeNull();
    expect(formatAgentUpdateTime("not-a-date")).toBeNull();
    expect(formatAgentUpdateTime(undefined)).toBeNull();
  });
});
