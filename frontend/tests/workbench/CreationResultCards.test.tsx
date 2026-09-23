import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  AgentCreationResultCard,
  SkillCreationResultCard,
} from "@/features/workbench/components/CreationResultCards";

const searchAgentInfo = vi.hoisted(() => vi.fn());
const fetchMyEditableSkills = vi.hoisted(() => vi.fn());
vi.mock("@/services/agentConfigService", () => ({ searchAgentInfo }));
vi.mock("@/services/skillRepositoryService", () => ({ fetchMyEditableSkills }));

beforeEach(() => {
  fetchMyEditableSkills.mockReset().mockResolvedValue({
    items: [],
    pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 },
  });
});

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
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存 Skill" })).toBeEnabled()
  );
  await userEvent.click(screen.getByRole("button", { name: "保存 Skill" }));
  expect(onSave).toHaveBeenCalledWith(payload);
});

it("restores a saved Skill card from the user's Skills after reopening history", async () => {
  fetchMyEditableSkills.mockResolvedValueOnce({
    items: [{ skill_id: 28, name: "invoice-helper" }],
    pagination: { page: 1, page_size: 100, total: 1, total_pages: 1 },
  });
  const onSave = vi.fn();
  render(
    <SkillCreationResultCard
      payload={{
        name: "invoice-helper",
        description: "Extract invoices",
        source: "custom",
        tags: [],
        content: "# Instructions",
        files: [],
      }}
      saved={false}
      onSave={onSave}
    />
  );
  expect(
    await screen.findByRole("link", { name: "查看我的 Skills" })
  ).toHaveAttribute("href", "/skill-space?tab=mine");
  expect(screen.queryByRole("button", { name: "保存 Skill" })).toBeNull();
  expect(onSave).not.toHaveBeenCalled();
  expect(fetchMyEditableSkills).toHaveBeenCalledWith(
    expect.objectContaining({ ownership: "created", search: "invoice-helper" })
  );
});

it("does not mistake a different named Skill for the saved draft", async () => {
  fetchMyEditableSkills.mockResolvedValueOnce({
    items: [{ skill_id: 29, name: "invoice-helper-v2" }],
    pagination: { page: 1, page_size: 100, total: 1, total_pages: 1 },
  });
  render(
    <SkillCreationResultCard
      payload={{
        name: "invoice-helper",
        description: "Extract invoices",
        source: "custom",
        tags: [],
        content: "# Instructions",
        files: [],
      }}
      saved={false}
      onSave={vi.fn()}
    />
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存 Skill" })).toBeEnabled()
  );
  expect(screen.queryByRole("link", { name: "查看我的 Skills" })).toBeNull();
});

it("prevents duplicate saving while the saved status is still being checked", async () => {
  let resolveLookup!: (value: unknown) => void;
  fetchMyEditableSkills.mockReturnValueOnce(
    new Promise((resolve) => {
      resolveLookup = resolve;
    })
  );
  const onSave = vi.fn();
  render(
    <SkillCreationResultCard
      payload={{
        name: "invoice-helper",
        description: "Extract invoices",
        source: "custom",
        tags: [],
        content: "# Instructions",
        files: [],
      }}
      saved={false}
      onSave={onSave}
    />
  );
  expect(screen.getByRole("button", { name: "保存 Skill" })).toBeDisabled();
  resolveLookup({
    items: [{ skill_id: 28, name: "invoice-helper" }],
    pagination: { page: 1, page_size: 100, total: 1, total_pages: 1 },
  });
  expect(
    await screen.findByRole("link", { name: "查看我的 Skills" })
  ).toBeInTheDocument();
  expect(onSave).not.toHaveBeenCalled();
});

it("does not offer Save when the Skill status lookup fails", async () => {
  fetchMyEditableSkills.mockRejectedValueOnce(new Error("network unavailable"));
  render(
    <SkillCreationResultCard
      payload={{
        name: "invoice-helper",
        description: "Extract invoices",
        source: "custom",
        tags: [],
        content: "# Instructions",
        files: [],
      }}
      saved={false}
      onSave={vi.fn()}
    />
  );
  expect(
    await screen.findByRole("button", { name: "重新查询 Skill 状态" })
  ).toBeEnabled();
  expect(screen.queryByRole("button", { name: "保存 Skill" })).toBeNull();
});
