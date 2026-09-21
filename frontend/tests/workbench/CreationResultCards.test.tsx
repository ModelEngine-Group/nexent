import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  AgentCreationResultCard,
  SkillCreationResultCard,
} from "@/features/workbench/components/CreationResultCards";

const searchAgentInfo = vi.hoisted(() => vi.fn());
vi.mock("@/services/agentConfigService", () => ({ searchAgentInfo }));

it("shows the completed Agent's summary and links to its development page", () => {
  render(
    <AgentCreationResultCard
      agentId={42}
      name="Invoice Agent"
      description="Processes invoices"
    />
  );
  expect(screen.getByText("Processes invoices")).toBeInTheDocument();
  const card = screen.getByRole("link", { name: /进入智能体开发/ });
  expect(card).toHaveClass("w-full");
  expect(card).not.toHaveClass("max-w-xl");
  expect(card).toHaveAttribute(
    "href",
    "/agents?agent_id=42"
  );
});

it("loads the generated Agent details when restored from a message", async () => {
  searchAgentInfo.mockResolvedValueOnce({
    success: true,
    data: {
      agent_id: 42,
      display_name: "智能客服助手",
      description: "回答售前与售后问题",
    },
  });
  render(<AgentCreationResultCard agentId={42} />);
  expect(await screen.findByText("智能客服助手")).toBeInTheDocument();
  expect(screen.getByText("回答售前与售后问题")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /进入智能体开发/ })).toHaveAttribute(
    "href",
    "/agents?agent_id=42"
  );
});

it("does not claim completion when only an Agent draft was saved", () => {
  render(
    <AgentCreationResultCard
      agentId={42}
      name="客服助手"
      completed={false}
    />
  );
  expect(screen.getByText("草稿已保存")).toBeInTheDocument();
  expect(screen.queryByText("草稿已生成")).not.toBeInTheDocument();
});

it("saves the generated Skill only when the user confirms", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const payload = {
    name: "invoice-helper",
    description: "Extract invoices",
    source: "custom",
    tags: [],
    content: "# Instructions",
    files: [],
  };
  render(
    <SkillCreationResultCard payload={payload} saved={false} onSave={onSave} />
  );
  expect(onSave).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "保存 Skill" }));
  expect(onSave).toHaveBeenCalledWith(payload);
});
