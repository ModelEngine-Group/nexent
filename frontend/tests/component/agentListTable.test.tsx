// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentListTable, {
  formatAgentUpdateTime,
} from "../../app/[locale]/agents/components/agent-list-table";
import type { Agent } from "@/types/agentConfig";

const session = vi.hoisted(() => ({ provider: "local" }));
const bulkDelete = vi.hoisted(() => ({
  isPending: false,
  mutateAsync: vi.fn(),
}));
const showNotice = vi.hoisted(() => vi.fn());
vi.mock("@/lib/uiNotices", () => ({ showInfoNotice: showNotice }));

vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: session.provider } }),
}));

vi.mock("@/hooks/agent/useAgentBulkDelete", () => ({
  useAgentBulkDelete: () => bulkDelete,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { column?: string }) => {
      if (key === "agentConfig.list.resizeColumn")
        return `Resize ${options?.column}`;
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
        "agentRepository.tag.marketing": "营销",
        "agentRepository.tag.customerService": "客服",
        "agentConfig.list.configure": "配置",
        "agentConfig.list.publish": "发布",
      };
      return translations[key] ?? key;
    },
  }),
}));

vi.mock("../../app/[locale]/agents/components/agent-config-actions", () => ({
  default: ({
    agentId,
    agentName,
    readOnly,
    variant,
    onManageVersions,
  }: {
    agentId: number;
    agentName: string;
    readOnly: boolean;
    variant: string;
    onManageVersions: (agentId: number) => void;
  }) => (
    <button
      type="button"
      data-agent-name={agentName}
      data-read-only={String(readOnly)}
      data-variant={variant}
      onClick={() => onManageVersions(agentId)}
    >
      更多
    </button>
  ),
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
  beforeEach(() => {
    session.provider = "local";
    bulkDelete.isPending = false;
    bulkDelete.mutateAsync.mockReset();
    showNotice.mockReset();
  });

  it.each([
    ["cas", "平台作者"],
    ["local", "刘晨"],
  ])(
    "preserves creator identity and resizable columns for a %s viewer",
    (provider, displayName) => {
      session.provider = provider;
      const agent = { ...firstAgent, author_cas_username: "平台作者" };
      render(
        <AgentListTable
          agents={[agent, { ...secondAgent, author: "Imported Author" }]}
          onOpen={vi.fn()}
          onConfigure={vi.fn()}
          onPublish={vi.fn()}
          onManageVersions={vi.fn()}
        />
      );
      const firstRow = screen
        .getByRole("button", { name: agent.display_name })
        .closest("tr")!;
      expect(within(firstRow).getByText(displayName)).toBeInTheDocument();
      expect(
        within(firstRow).queryByText(provider === "cas" ? "刘晨" : "平台作者")
      ).not.toBeInTheDocument();
      expect(screen.getByText("Imported Author")).toBeInTheDocument();
      expect(screen.getAllByRole("separator")).toHaveLength(6);
      expect(
        screen.getByRole("columnheader", { name: "操作" })
      ).not.toHaveClass("sticky");
      expect(agent.author).toBe("刘晨");
      expect(agent.author_cas_username).toBe("平台作者");
    }
  );
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
      screen
        .getAllByRole("columnheader")
        .map((header) => header.textContent)
        .filter(Boolean)
    ).toEqual(["名称", "类型", "描述", "状态", "创建人", "更新时间", "操作"]);
    const table = screen.getAllByRole("table")[0];
    expect(table).toBeInTheDocument();
    expect(table).toHaveAttribute("data-slot", "table");

    const rows = [firstAgent, secondAgent].map((agent) =>
      screen.getByRole("button", { name: agent.display_name }).closest("tr")!
    );
    expect(within(rows[0]).getByText("刘晨")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2026-09-18")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("2026-09-17")).not.toBeInTheDocument();
    expect(within(rows[1]).getAllByText("-")).toHaveLength(2);
    expect(getByTestId("agent-list-table-scroll")).toHaveClass("min-h-0");
    expect(table.querySelector(".ant-pagination")).toBeNull();
    expect(screen.getByRole("columnheader", { name: "操作" })).not.toHaveClass(
      "sticky"
    );
  });

  it.each([
    ["marketing", "营销"],
    ["customer_service", "客服"],
    ["database", "database"],
  ])("renders tag %s using its display label %s", (rawTag, displayLabel) => {
    render(
      <AgentListTable
        agents={[{ ...firstAgent, tags: [rawTag] }]}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );
    expect(screen.getByText(displayLabel)).toBeInTheDocument();
    if (rawTag !== displayLabel) {
      expect(
        screen.queryByText(rawTag, { exact: true })
      ).not.toBeInTheDocument();
    }
  });

  it("keeps detail, configure, publish, and version actions connected", () => {
    const onOpen = vi.fn();
    const onConfigure = vi.fn();
    const onPublish = vi.fn();
    const onManageVersions = vi.fn();
    render(
      <AgentListTable
        agents={[firstAgent, secondAgent]}
        onOpen={onOpen}
        onConfigure={onConfigure}
        onPublish={onPublish}
        onManageVersions={onManageVersions}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "健康小助手" }));
    fireEvent.click(screen.getAllByRole("button", { name: "配置" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "发布" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "更多" })[0]);
    expect(onManageVersions).toHaveBeenCalledWith(1);
    expect(screen.getAllByRole("button", { name: "发布" })).toHaveLength(1);
    expect(onOpen).toHaveBeenCalledWith(firstAgent);
    expect(onConfigure).toHaveBeenCalledWith(1);
    expect(onPublish).toHaveBeenCalledWith(2);
  });

  it("preserves action permissions and complete long-name hints", () => {
    const longName = "very long agent name ".repeat(12);
    render(
      <AgentListTable
        agents={[
          { ...firstAgent, display_name: longName, permission: "READ_ONLY" },
        ]}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );
    expect(
      screen.getByRole("button", { name: longName.trim() })
    ).toHaveAttribute("title", longName);
    const actions = screen.getByRole("button", { name: "更多" });
    expect(actions).toHaveAttribute("data-agent-name", longName);
    expect(actions).toHaveAttribute("data-read-only", "true");
    expect(actions).toHaveAttribute("data-variant", "table");
  });

  it("requires confirmation and retains failed selections after partial deletion", async () => {
    bulkDelete.mutateAsync.mockResolvedValue({
      deleted: [firstAgent],
      failed: [secondAgent],
    });
    render(
      <AgentListTable
        agents={[firstAgent, secondAgent]}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "table.selectAll" }));
    expect(bulkDelete.mutateAsync).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "agentConfig.list.bulkDelete" })
    );
    expect(bulkDelete.mutateAsync).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "common.confirm",
      })
    );
    await waitFor(() => expect(showNotice).toHaveBeenCalledOnce());
    expect(bulkDelete.mutateAsync).toHaveBeenCalledExactlyOnceWith([
      firstAgent,
      secondAgent,
    ]);
    const rowCheckbox = (name: string) =>
      within(screen.getByRole("button", { name }).closest("tr")!).getByRole(
        "checkbox"
      );
    expect(rowCheckbox(firstAgent.display_name!)).not.toBeChecked();
    expect(rowCheckbox(secondAgent.display_name!)).toBeChecked();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancels deletion without a request and excludes read-only rows", () => {
    render(
      <AgentListTable
        agents={[firstAgent, { ...secondAgent, permission: "READ_ONLY" }]}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );
    const readOnlyRow = screen
      .getByRole("button", { name: secondAgent.display_name })
      .closest("tr")!;
    expect(within(readOnlyRow).getByRole("checkbox")).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "table.selectAll" }));
    fireEvent.click(
      screen.getByRole("button", { name: "agentConfig.list.bulkDelete" })
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(firstAgent.display_name!)
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByText(secondAgent.display_name!)
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "common.cancel" })
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(bulkDelete.mutateAsync).not.toHaveBeenCalled();
  });

  it("formats only valid update timestamps", () => {
    expect(formatAgentUpdateTime("2026-09-18T10:30:00")).toBe("2026-09-18");
    expect(formatAgentUpdateTime("2026-02-30T10:30:00")).toBeNull();
    expect(formatAgentUpdateTime("not-a-date")).toBeNull();
    expect(formatAgentUpdateTime(undefined)).toBeNull();
  });
});

describe("Agent table presentation", () => {
  it("renders the shared table with column resize controls", () => {
    render(
      <AgentListTable
        agents={[firstAgent]}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("separator")).toHaveLength(6);
  });
});
