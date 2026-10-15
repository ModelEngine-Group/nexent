// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

vi.mock("@/app/i18n", () => ({
  default: { t: (key: string) => key, language: "zh" },
}));
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AgentListTable, {
  formatAgentUpdateTime,
} from "@/app/[locale]/agents/components/agent-list-table";
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

vi.mock("@/app/[locale]/agents/components/agent-config-actions", () => ({
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

describe("[AGENT-LIST-D1-001] AgentListTable", () => {
  it("renders the specified columns and uses only update_time for the date", () => {
    const { getByTestId } = render(
      <AgentListTable
        agents={[firstAgent, secondAgent]}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />,
    );

    expect(
      screen
        .getAllByRole("columnheader")
        .map((header) => header.textContent)
        .filter(Boolean),
    ).toEqual(["名称", "类型", "描述", "状态", "创建人", "更新时间", "操作"]);
    const table = screen.getAllByRole("table")[0];
    expect(table).toBeInTheDocument();
    expect(table.closest(".agent-list-table")).toBeInTheDocument();

    const rows = [firstAgent, secondAgent].map((agent) =>
      screen.getByRole("button", { name: agent.display_name }).closest("tr")!,
    );
    expect(within(rows[0]).getByText("刘晨")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2026-09-18")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("2026-09-17")).not.toBeInTheDocument();
    expect(within(rows[1]).getAllByText("-")).toHaveLength(2);
    expect(getByTestId("agent-list-table-scroll")).toHaveClass(
      "flex-1",
      "min-h-0",
    );
    expect(
      table.closest(".agent-list-table")?.querySelector(".ant-pagination"),
    ).toBeNull();
    expect(
      screen.getByRole("columnheader", { name: "\u64cd\u4f5c" }),
    ).toHaveClass("ant-table-cell-fix-end");
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
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "健康小助手" }));
    fireEvent.click(screen.getAllByRole("button", { name: "配置" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "发布" })[0]);
    expect(onOpen).toHaveBeenCalledWith(firstAgent);
    expect(onConfigure).toHaveBeenCalledWith(1);
    expect(onPublish).toHaveBeenCalledWith(2);
  });

  it("resizes real header cells while preserving row actions", () => {
    const onConfigure = vi.fn();
    render(
      <AgentListTable
        agents={[firstAgent]}
        onOpen={vi.fn()}
        onConfigure={onConfigure}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />,
    );
    const handles = screen.getAllByRole("separator");
    expect(handles).toHaveLength(7);
    expect(handles[0]).toHaveAttribute("aria-valuenow", "240");
    fireEvent.keyDown(handles[0], { key: "ArrowRight" });
    expect(handles[0]).toHaveAttribute("aria-valuenow", "256");
    for (let index = 0; index < 12; index += 1) {
      fireEvent.keyDown(handles[0], { key: "ArrowLeft" });
    }
    expect(handles[0]).toHaveAttribute("aria-valuenow", "180");
    fireEvent.click(screen.getByRole("button", { name: "\u914d\u7f6e" }));
    expect(onConfigure).toHaveBeenCalledWith(1);
  });

  it("formats only valid update timestamps", () => {
    expect(formatAgentUpdateTime("2026-09-18T10:30:00")).toBe("2026-09-18");
    expect(formatAgentUpdateTime("2026-02-30T10:30:00")).toBeNull();
    expect(formatAgentUpdateTime("not-a-date")).toBeNull();
    expect(formatAgentUpdateTime(undefined)).toBeNull();
  });
});
