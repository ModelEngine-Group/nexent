// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import AgentListCard, {
  formatAgentListDate,
} from "../../app/[locale]/agents/components/agent-list-card";
import type { Agent } from "@/types/agentConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { date?: string }) => {
      const translations: Record<string, string> = {
        "agentConfig.list.configure": "配置",
        "agentConfig.list.publish": "发布",
        "agentConfig.list.online": "已上线",
        "agentConfig.list.offline": "未上线",
        "agentRepository.tag.marketing": "营销",
        "agentRepository.tag.customerService": "客服",
        "agentRepository.card.noDescription": "暂无描述",
      };
      if (key === "agentConfig.list.updatedAt") return `更新于${options?.date}`;
      if (key === "agentConfig.list.createdAt") return `创建于${options?.date}`;
      return translations[key] ?? key;
    },
  }),
}));

vi.mock("@/app/[locale]/agents/components/agent-avatar", () => ({
  default: () => <div data-testid="agent-avatar" />,
}));

vi.mock("../../app/[locale]/agents/components/agent-config-actions", () => ({
  default: function MockAgentConfigActions({
    agentId,
    readOnly,
    onConfigure,
    onPublish,
    onManageVersions,
  }: {
    agentId: number;
    readOnly: boolean;
    onConfigure: (agentId: number) => void;
    onPublish: (agentId: number) => void;
    onManageVersions: (agentId: number) => void;
  }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          更多
        </button>
        {open && (
          <>
            <button type="button" onClick={() => onConfigure(agentId)}>
              配置
            </button>
            <button
              type="button"
              disabled={readOnly}
              onClick={() => onPublish(agentId)}
            >
              发布
            </button>
            <button type="button" onClick={() => onManageVersions(agentId)}>
              版本管理
            </button>
          </>
        )}
      </>
    );
  },
}));

const agent = {
  id: "42",
  name: "health_agent",
  display_name: "健康小助手",
  description: "一个专业、全面的健康咨询智能体",
  tags: ["医疗"],
  create_time: "2026-01-23T12:00:00",
} as Agent;

describe("AgentListCard", () => {
  it("renders the measured card structure and data-backed metadata", () => {
    const { container } = render(
      <AgentListCard
        agent={agent}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );

    expect(container.querySelector("article")).toHaveClass(
      "h-[180px]",
      "rounded-[12px]",
      "px-6",
      "py-4"
    );
    expect(screen.getByText("健康小助手")).toHaveClass(
      "text-[16px]",
      "leading-6"
    );
    expect(screen.getByText("医疗").closest(".ant-tag")).toHaveClass(
      "!h-[22px]",
      "!rounded-full"
    );
    expect(screen.getByText("一个专业、全面的健康咨询智能体")).toHaveClass(
      "text-[12px]",
      "leading-5",
      "line-clamp-2"
    );
    expect(screen.getByText("创建于2026-01-23")).toBeInTheDocument();
    expect(screen.getByText("未上线")).toBeInTheDocument();
    expect(screen.getByTestId("agent-card-footer")).toHaveClass(
      "w-full",
      "justify-between"
    );
    expect(screen.getByTestId("agent-card-date")).toHaveClass("flex-1");
    expect(screen.getByTestId("agent-card-status")).toHaveClass("shrink-0");
  });

  it.each([
    ["marketing", "营销"],
    ["customer_service", "客服"],
    ["database", "database"],
  ])("renders tag %s using its display label %s", (rawTag, displayLabel) => {
    render(
      <AgentListCard
        agent={{ ...agent, tags: [rawTag] }}
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

  it("keeps detail, configuration, and publish navigation distinct", () => {
    const onOpen = vi.fn();
    const onConfigure = vi.fn();
    const onPublish = vi.fn();
    const onManageVersions = vi.fn();
    render(
      <AgentListCard
        agent={agent}
        onOpen={onOpen}
        onConfigure={onConfigure}
        onPublish={onPublish}
        onManageVersions={onManageVersions}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "健康小助手" }));
    fireEvent.click(screen.getByRole("button", { name: "更多" }));
    fireEvent.click(screen.getByRole("button", { name: "配置" }));
    fireEvent.click(screen.getByRole("button", { name: "发布" }));
    fireEvent.click(screen.getByRole("button", { name: "版本管理" }));
    expect(onOpen).toHaveBeenCalledWith(agent);
    expect(onConfigure).toHaveBeenCalledWith(42);
    expect(onPublish).toHaveBeenCalledWith(42);
    expect(onManageVersions).toHaveBeenCalledWith(42);
  });

  it("keeps publishing disabled for a read-only Agent in the more menu", () => {
    const onPublish = vi.fn();
    render(
      <AgentListCard
        agent={{ ...agent, permission: "READ_ONLY" } as Agent}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={onPublish}
        onManageVersions={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "更多" }));
    const publish = screen.getByRole("button", { name: "发布" });
    expect(publish).toBeDisabled();
    fireEvent.click(publish);
    expect(onPublish).not.toHaveBeenCalled();
  });

  it("prefers an update timestamp without inventing one", () => {
    expect(formatAgentListDate(agent)).toEqual({
      date: "2026-01-23",
      isUpdate: false,
    });
    expect(
      formatAgentListDate({
        ...agent,
        update_time: "2026-02-04T09:30:00",
      })
    ).toEqual({ date: "2026-02-04", isUpdate: true });
    expect(
      formatAgentListDate({ ...agent, create_time: undefined })
    ).toBeNull();
  });

  it("recovers a tag from a stringified array payload without throwing", () => {
    render(
      <AgentListCard
        agent={{ ...agent, tags: "['医疗', '健康']" as unknown as string[] }}
        onOpen={vi.fn()}
        onConfigure={vi.fn()}
        onPublish={vi.fn()}
        onManageVersions={vi.fn()}
      />
    );

    expect(screen.getByText("医疗")).toBeInTheDocument();
  });
});
