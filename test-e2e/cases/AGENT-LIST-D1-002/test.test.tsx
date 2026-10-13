vi.mock("@/app/i18n", () => ({ default: { t: (key: string) => key, language: "zh" } }));
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AgentListCard, {
  formatAgentListDate,
} from "@/app/[locale]/agents/components/agent-list-card";
import type { Agent } from "@/types/agentConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { date?: string }) => {
      const labels: Record<string, string> = {
        "agentConfig.list.configure": "配置",
        "agentConfig.list.publish": "发布",
        "agentConfig.list.online": "已上线",
        "agentConfig.list.offline": "未上线",
        "agentRepository.card.noDescription": "暂无描述",
      };
      if (key === "agentConfig.list.updatedAt") return `更新于${options?.date}`;
      if (key === "agentConfig.list.createdAt") return `创建于${options?.date}`;
      return labels[key] ?? key;
    },
  }),
}));

vi.mock("@/app/agents/components/agent-avatar", () => ({
  default: () => <span aria-hidden="true" />,
}));

vi.mock("@/app/agents/components/agent-config-actions", () => ({
  default: ({
    agentId,
    readOnly,
    onManageVersions,
  }: {
    agentId: number;
    readOnly: boolean;
    onManageVersions: (agentId: number) => void;
  }) => (
    <button
      type="button"
      data-read-only={readOnly}
      onClick={() => onManageVersions(agentId)}
    >
      更多
    </button>
  ),
}));

const publishedAgent = {
  id: "42",
  name: "health_agent",
  display_name: "健康小助手",
  description: "一个专业、全面的健康咨询智能体，提供可靠、实用的健康信息。",
  tags: ["医疗"],
  create_time: "2026-01-23T12:00:00",
  update_time: "2026-02-04T09:30:00",
  current_version_no: 2,
  permission: "EDIT",
} as Agent;

function renderCard(agent: Agent) {
  const callbacks = {
    onOpen: vi.fn(),
    onConfigure: vi.fn(),
    onPublish: vi.fn(),
    onManageVersions: vi.fn(),
  };
  render(<AgentListCard agent={agent} {...callbacks} />);
  return callbacks;
}

describe("[AGENT-LIST-D1-002] measured Agent card metadata and callbacks", () => {
  it("renders published metadata without turning the status dot into a control", () => {
    const callbacks = renderCard(publishedAgent);

    expect(
      screen.getByRole("button", { name: "健康小助手" }),
    ).toBeInTheDocument();
    expect(screen.getByText(publishedAgent.description)).toBeInTheDocument();
    expect(screen.getByText("医疗")).toBeInTheDocument();
    expect(screen.getByText("更新于2026-02-04")).toBeInTheDocument();
    expect(screen.queryByText("创建于2026-01-23")).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-card-status")).toHaveTextContent("已上线");
    const dot = screen.getByTestId("agent-card-status-dot");
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect(dot).not.toHaveAttribute("role");
    expect(dot).not.toHaveAttribute("tabindex");
    expect(dot.closest("button")).toBeNull();
    for (const callback of Object.values(callbacks))
      expect(callback).not.toHaveBeenCalled();
  });

  it("keeps creation dates, offline status and publication protection truthful", () => {
    const readOnlyAgent = {
      ...publishedAgent,
      id: "43",
      display_name: "资料助手",
      tags: [],
      update_time: undefined,
      current_version_no: undefined,
      permission: "READ_ONLY",
    } as Agent;
    const callbacks = renderCard(readOnlyAgent);

    expect(screen.getByText("创建于2026-01-23")).toBeInTheDocument();
    expect(screen.queryByText(/更新于/)).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-card-status")).toHaveTextContent("未上线");
    expect(screen.queryByText("医疗")).not.toBeInTheDocument();
    const publish = screen.getByRole("button", { name: "发布" });
    expect(publish).toBeDisabled();
    fireEvent.click(publish);
    expect(callbacks.onPublish).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "更多" })).toHaveAttribute(
      "data-read-only",
      "true",
    );
  });

  it("uses localized missing-value fallbacks without inventing a date or category", () => {
    const missingAgent = {
      ...publishedAgent,
      name: "fallback_agent",
      display_name: undefined,
      description: "",
      tags: [],
      create_time: undefined,
      update_time: undefined,
      current_version_no: undefined,
    } as Agent;
    renderCard(missingAgent);

    expect(
      screen.getByRole("button", { name: "fallback_agent" }),
    ).toBeInTheDocument();
    expect(screen.getByText("暂无描述")).toBeInTheDocument();
    expect(screen.getByText("-")).toBeInTheDocument();
    expect(screen.queryByText(/创建于|更新于/)).not.toBeInTheDocument();
    expect(screen.queryByText("医疗")).not.toBeInTheDocument();
    expect(formatAgentListDate(missingAgent)).toBeNull();
  });

  it("preserves independent detail, configure, publish and version-menu callbacks", () => {
    const callbacks = renderCard(publishedAgent);

    fireEvent.click(screen.getByRole("button", { name: "健康小助手" }));
    expect(callbacks.onOpen).toHaveBeenCalledExactlyOnceWith(publishedAgent);
    expect(callbacks.onConfigure).not.toHaveBeenCalled();
    expect(callbacks.onPublish).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "配置" }));
    fireEvent.click(screen.getByRole("button", { name: "发布" }));
    fireEvent.click(screen.getByRole("button", { name: "更多" }));
    expect(callbacks.onConfigure).toHaveBeenCalledExactlyOnceWith(42);
    expect(callbacks.onPublish).toHaveBeenCalledExactlyOnceWith(42);
    expect(callbacks.onManageVersions).toHaveBeenCalledExactlyOnceWith(42);
  });
});
