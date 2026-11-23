import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Agent } from "@/types/agentConfig";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CreateAgentModal from "@/components/agent/CreateAgentModal";
import {
  checkAgentNameConflictBatch,
  fetchAgentList,
  updateAgentInfo,
} from "@/services/agentConfigService";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { max?: number }) => {
      const translations: Record<string, string> = {
        "chat.agentLanding.createAgent": "创建智能体",
        "agentConfig.createModal.close": "关闭创建智能体弹窗",
        "agentConfig.createModal.submit": "创建",
        "agentConfig.createModal.namePlaceholder": "我的智能体02",
        "agentConfig.createModal.template.create": "从模板创建",
        "agentConfig.createModal.template.repository": "智能体仓库",
        "agentConfig.createModal.templates.empty": "暂无可用的智能体模板",
        "agentConfig.createModal.templates.loadFailed": "模板加载失败",
        "common.retry": "重试",
        "agent.displayName": "智能体名称",
        "agent.displayNamePlaceholder": "请输入智能体名称",
        "agent.validation.displayNameRequired": "请输入智能体名称",
        "agent.validation.displayNameMaxLength": `智能体名称不能超过 ${options?.max} 个字符`,
        "agent.validation.displayNameDuplicate": "智能体名称已存在",
        "agent.validation.displayNameConflictCheckFailed":
          "智能体名称重复校验失败",
        "common.cancel": "取消",
        "common.confirm": "确认",
        "businessLogic.config.error.saveFailed": "保存失败",
      };
      return translations[key] ?? key;
    },
  }),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ locale: "zh" }),
}));

vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { email: "test@example.com" } }),
}));

vi.mock("@/services/agentConfigService", () => ({
  checkAgentNameConflictBatch: vi.fn(),
  fetchAgentList: vi.fn(),
  updateAgentInfo: vi.fn(),
}));

const apiAgent: Agent = {
  id: "72",
  name: "report-agent",
  display_name: "接口报告助手",
  description: "接口返回的真实描述",
  tags: ["报告"],
  model: "",
  max_step: 15,
  provide_run_summary: false,
  tools: [],
};

function mount(open = true) {
  const onCreated = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = (isOpen: boolean) => (
    <QueryClientProvider client={client}>
      <App>
        <CreateAgentModal
          open={isOpen}
          onCancel={vi.fn()}
          onCreated={onCreated}
        />
      </App>
    </QueryClientProvider>
  );
  const view = render(tree(open));
  return {
    onCreated,
    reopen: () => {
      view.rerender(tree(false));
      view.rerender(tree(true));
    },
  };
}

describe("CreateAgentModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAgentList).mockResolvedValue({
      success: true,
      message: "success",
      data: [apiAgent],
    });
    vi.mocked(checkAgentNameConflictBatch).mockResolvedValue({
      success: true,
      message: "success",
      data: [{}],
    } as never);
    vi.mocked(updateAgentInfo).mockResolvedValue({
      success: true,
      message: "success",
      data: { agent_id: 42 },
    } as never);
  });

  it("renders API-only templates with the existing high-fidelity dimensions", async () => {
    mount();
    expect(await screen.findByText(apiAgent.display_name!)).toHaveClass(
      "font-medium"
    );
    expect(screen.getByText(apiAgent.description)).toBeInTheDocument();
    expect(screen.getByText("报告")).toHaveClass("text-[#393939]");
    expect(screen.queryByText("心肌病筛查助手")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { pressed: false })).toHaveLength(1);
    expect(document.querySelector(".ant-modal")).toHaveStyle({
      width: "560px",
    });
    expect(document.querySelector(".ant-modal-container")).toHaveStyle({
      maxHeight: "572px",
    });
    expect(document.querySelector("[data-template-list]")).toHaveClass(
      "overflow-y-auto",
      "max-h-[368px]"
    );
    expect(screen.getByRole("link", { name: /智能体仓库/ })).toHaveAttribute(
      "href",
      "/zh/agent-space"
    );
  });

  it("creates once with the selected API description and the user's trimmed name", async () => {
    const user = userEvent.setup();
    const { onCreated } = mount();
    await user.click(
      await screen.findByRole("button", { name: /接口报告助手/ })
    );
    await user.type(
      screen.getByPlaceholderText("我的智能体02"),
      "  我的新智能体  "
    );
    await user.click(screen.getByRole("button", { name: /^创建$/ }));
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith({
        agentId: 42,
        displayName: "我的新智能体",
      })
    );
    expect(updateAgentInfo).toHaveBeenCalledTimes(1);
    expect(updateAgentInfo).toHaveBeenCalledWith(
      expect.objectContaining({
        display_name: "我的新智能体",
        description: apiAgent.description,
        author: "test@example.com",
      })
    );
  });

  it("clears selection on a second click and on reopening", async () => {
    const user = userEvent.setup();
    const view = mount();
    const card = await screen.findByRole("button", { name: /接口报告助手/ });
    await user.click(card);
    expect(card).toHaveAttribute("aria-pressed", "true");
    await user.click(card);
    expect(card).toHaveAttribute("aria-pressed", "false");
    await user.click(card);
    view.reopen();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /接口报告助手/ })
      ).toHaveAttribute("aria-pressed", "false")
    );
    await user.type(screen.getByPlaceholderText("我的智能体02"), "空白智能体");
    await user.click(screen.getByRole("button", { name: /^创建$/ }));
    await waitFor(() =>
      expect(updateAgentInfo).toHaveBeenCalledWith(
        expect.objectContaining({ description: "" })
      )
    );
  });

  it("shows empty API data without static templates and still permits blank creation", async () => {
    vi.mocked(fetchAgentList).mockResolvedValue({
      success: true,
      data: [],
      message: "success",
    });
    const user = userEvent.setup();
    mount();
    expect(await screen.findByText("暂无可用的智能体模板")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { pressed: false })
    ).not.toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("我的智能体02"), "空白创建");
    await user.click(screen.getByRole("button", { name: /^创建$/ }));
    await waitFor(() =>
      expect(updateAgentInfo).toHaveBeenCalledWith(
        expect.objectContaining({ description: "" })
      )
    );
  });

  it("offers explicit retry after an API failure without fabricated fallback data", async () => {
    vi.mocked(fetchAgentList).mockResolvedValueOnce({
      success: false,
      data: [],
      message: "Controlled failure",
    });
    const user = userEvent.setup();
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("模板加载失败");
    expect(
      screen.queryByRole("button", { pressed: false })
    ).not.toBeInTheDocument();
    expect(updateAgentInfo).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText(apiAgent.display_name!)).toBeInTheDocument();
    expect(fetchAgentList).toHaveBeenCalledTimes(2);
  });

  it("does not fetch while closed", () => {
    mount(false);
    expect(fetchAgentList).not.toHaveBeenCalled();
  });

  it("uses API name fallback and does not invent tags or include subagents", async () => {
    vi.mocked(fetchAgentList).mockResolvedValue({
      success: true,
      message: "success",
      data: [
        { ...apiAgent, display_name: undefined, tags: [] },
        {
          ...apiAgent,
          id: "73",
          display_name: "隐藏子智能体",
          is_main_agent: false,
        },
      ],
    });
    mount();
    expect(await screen.findByText("report-agent")).toBeInTheDocument();
    expect(screen.queryByText("医疗")).not.toBeInTheDocument();
    expect(screen.queryByText("隐藏子智能体")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { pressed: false })).toHaveLength(1);
  });
});
