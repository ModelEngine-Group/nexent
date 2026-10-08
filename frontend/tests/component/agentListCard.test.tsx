import { fireEvent, render, screen } from "@testing-library/react";
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

vi.mock("@/app/[locale]/agents/components/agent-config-actions", () => ({
  default: () => <button type="button">更多</button>,
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
      "h-[148px]",
      "rounded-[12px]",
      "px-6",
      "py-4"
    );
    expect(screen.getByText("健康小助手")).toHaveClass(
      "text-[16px]",
      "leading-6"
    );
    expect(screen.getByText("医疗")).toHaveClass("h-[22px]", "rounded-[4px]");
    expect(screen.getByText("一个专业、全面的健康咨询智能体")).toHaveClass(
      "text-[12px]",
      "leading-5",
      "line-clamp-2"
    );
    expect(screen.getByText("创建于2026-01-23")).toBeInTheDocument();
    expect(screen.getByText("未上线")).toBeInTheDocument();
  });

  it("keeps detail, configuration, and publish navigation distinct", () => {
    const onOpen = vi.fn();
    const onConfigure = vi.fn();
    const onPublish = vi.fn();
    render(
      <AgentListCard
        agent={agent}
        onOpen={onOpen}
        onConfigure={onConfigure}
        onPublish={onPublish}
        onManageVersions={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "健康小助手" }));
    fireEvent.click(screen.getByRole("button", { name: "配置" }));
    fireEvent.click(screen.getByRole("button", { name: "发布" }));
    expect(onOpen).toHaveBeenCalledWith(agent);
    expect(onConfigure).toHaveBeenCalledWith(42);
    expect(onPublish).toHaveBeenCalledWith(42);
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
});
