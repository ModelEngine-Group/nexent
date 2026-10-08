import { App } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CreateAgentModal from "@/components/agent/CreateAgentModal";
import {
  checkAgentNameConflictBatch,
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
        "agentConfig.createModal.templates.medicalTag": "医疗",
        "agentConfig.createModal.templates.cardiomyopathy.title":
          "心肌病筛查助手",
        "agentConfig.createModal.templates.cardiomyopathy.description":
          "辅助进行心肌病相关信息筛查。",
        "agentConfig.createModal.templates.medicationSafety.title":
          "用药安全顾问",
        "agentConfig.createModal.templates.medicationSafety.description":
          "提供用药安全相关的辅助建议。",
        "agentConfig.createModal.templates.healthReport.title":
          "体检报告解读师",
        "agentConfig.createModal.templates.healthReport.description":
          "辅助理解体检报告中的关键指标。",
        "agentConfig.createModal.templates.medicalLiterature.title":
          "医学文献速读员",
        "agentConfig.createModal.templates.medicalLiterature.description":
          "帮助快速梳理医学文献重点。",
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
  updateAgentInfo: vi.fn(),
}));

describe("CreateAgentModal", () => {
  beforeEach(() => {
    vi.mocked(checkAgentNameConflictBatch).mockResolvedValue({
      success: true,
      data: [{}],
    } as never);
    vi.mocked(updateAgentInfo).mockResolvedValue({
      success: true,
      data: { agent_id: 42 },
    } as never);
  });

  it("renders the high-fidelity dimensions and optional template catalog", () => {
    render(
      <App>
        <CreateAgentModal open onCancel={vi.fn()} onCreated={vi.fn()} />
      </App>
    );

    expect(screen.getByText("创建智能体")).toBeInTheDocument();
    expect(document.querySelector(".ant-modal")).toHaveStyle({
      width: "560px",
    });
    expect(document.querySelector(".ant-modal-container")).toHaveStyle({
      maxHeight: "572px",
    });
    expect(screen.getAllByRole("button", { pressed: false })).toHaveLength(4);
    expect(screen.getByText("从模板创建")).toBeInTheDocument();
    expect(screen.getByText("从模板创建")).toHaveClass("text-[#191919]");
    expect(screen.getAllByText("医疗")[0]).toHaveClass(
      "text-[#393939]",
      "bg-[rgba(25,25,25,0.05)]"
    );
    expect(screen.getAllByText("心肌病筛查助手")[0]).toHaveClass("font-medium");
    expect(document.querySelectorAll("[data-template-icon]")).toHaveLength(4);
    expect(
      document.querySelectorAll("[data-template-description]")
    ).toHaveLength(4);
    expect(document.querySelector(".ant-modal-container")).toHaveClass(
      "!overflow-hidden"
    );
    expect(document.querySelector(".ant-modal-body")).toHaveClass(
      "!overflow-hidden",
      "!max-h-none",
      "!pb-0"
    );
    expect(document.querySelector("[data-template-list]")).toHaveClass(
      "overflow-y-auto",
      "max-h-[368px]",
      "min-h-0",
      "flex-1"
    );
    expect(document.querySelector(".ant-modal-container")).toHaveClass(
      "!border-[#c9c9c9]"
    );
    expect(screen.getByRole("link", { name: /智能体仓库/ })).toHaveAttribute(
      "href",
      "/zh/agent-space"
    );
    expect(screen.getByRole("button", { name: "创建", exact: true })).toHaveClass(
      "!mt-[30px]"
    );
  });

  it("creates with a selected template and allows the selection to be cleared", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();

    render(
      <App>
        <CreateAgentModal open onCancel={vi.fn()} onCreated={onCreated} />
      </App>
    );

    const firstTemplate = screen.getAllByRole("button", { pressed: false })[0];
    await user.click(firstTemplate);
    expect(firstTemplate).toHaveAttribute("aria-pressed", "true");
    expect(firstTemplate).toHaveClass("!border-[#2673e5]");
    await user.click(firstTemplate);
    expect(firstTemplate).toHaveAttribute("aria-pressed", "false");

    await user.type(
      screen.getByPlaceholderText("我的智能体02"),
      "我的智能体02"
    );
    await user.click(screen.getByRole("button", { name: "创建", exact: true }));

    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith({
        agentId: 42,
        displayName: "我的智能体02",
      })
    );
    expect(updateAgentInfo).toHaveBeenCalledWith(
      expect.objectContaining({
        display_name: "我的智能体02",
        description: "",
        author: "test@example.com",
      })
    );
  });
});
