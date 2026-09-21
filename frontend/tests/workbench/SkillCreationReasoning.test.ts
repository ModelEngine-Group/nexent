import { expect, it } from "vitest";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import type { ApiConversationDetail } from "@/types/conversation";

async function restoreSkillTurn(units: Array<{ type: string; content: string }>) {
  const detail = {
    conversation_id: "42",
    conversation_title: "创建合同审查技能",
    workbench_config: { mode: "skill_create" },
    message: [{ role: "assistant", message_id: 5, message: units }],
  } as ApiConversationDetail;
  const adapter = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  );
  const history = await adapter.load();
  return history.messages[0]?.message.content ?? [];
}

it("does not restore a Reasoning card from a bare Skill step marker", async () => {
  const content = await restoreSkillTurn([
    { type: "final_answer", content: "技能草稿已生成。" },
    { type: "step_count", content: "**步骤 1**" },
  ]);
  expect(content.some((part) => part.type === "reasoning")).toBe(false);
  expect(content.some((part) => part.type === "text")).toBe(true);
});

it("preserves real Skill reasoning while hiding the bare step marker", async () => {
  const content = await restoreSkillTurn([
    { type: "step_count", content: "**步骤 1**" },
    { type: "model_output_thinking", content: "先整理合同审查规则。" },
    { type: "final_answer", content: "技能草稿已生成。" },
  ]);
  const reasoning = content.filter((part) => part.type === "reasoning");
  expect(reasoning).toHaveLength(1);
  expect(reasoning[0]).toMatchObject({ text: "先整理合同审查规则。" });
});

it("reassembles streamed Skill summary fragments into one historical Markdown part", async () => {
  const content = await restoreSkillTurn([
    { type: "summary", content: "已为你创建「合同" },
    { type: "summary", content: "审查」技能。\n\n**功能亮点：**\n" },
    { type: "summary", content: "- 提取合同主体、金额与期限" },
    { type: "done", content: "" },
  ]);
  expect(content.filter((part) => part.type === "text")).toEqual([
    expect.objectContaining({
      text: "已为你创建「合同审查」技能。\n\n**功能亮点：**\n- 提取合同主体、金额与期限",
    }),
  ]);
});

it("keeps the Skill creation summary at the end of the restored answer", async () => {
  const content = await restoreSkillTurn([
    { type: "summary", content: "技能创建完成。" },
    { type: "model_output_thinking", content: "检查生成内容。" },
    { type: "final_answer", content: "执行已完成。" },
  ]);
  expect(content.at(-1)).toMatchObject({ type: "text", text: "技能创建完成。" });
});

it("discards rolled-back Skill summary and file fragments during history replay", async () => {
  const content = await restoreSkillTurn([
    { type: "summary", content: "技能" },
    {
      type: "model_attempt_control",
      content: JSON.stringify({
        type: "model_attempt_control",
        phase: "begin",
        attempt_id: "attempt-1",
      }),
    },
    { type: "summary", content: "错误内容" },
    {
      type: "file_content",
      content: JSON.stringify({ path: "example.md", content: "错误文件" }),
    },
    {
      type: "model_attempt_control",
      content: JSON.stringify({
        type: "model_attempt_control",
        phase: "rollback",
        attempt_id: "attempt-1",
      }),
    },
    { type: "summary", content: "已生成" },
    {
      type: "file_content",
      content: JSON.stringify({ path: "example.md", content: "正确文件" }),
    },
  ]);
  expect(content.filter((part) => part.type === "text")).toEqual([
    expect.objectContaining({ text: "技能已生成" }),
  ]);
  expect(content).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        type: "data",
        name: "nl2skill-file",
        data: expect.objectContaining({ path: "example.md", content: "正确文件" }),
      }),
    ])
  );
});

it("restores retried creation answers as sibling variants of one user turn", async () => {
  const detail = {
    conversation_id: "42",
    workbench_config: { mode: "skill_create" },
    message: [
      { role: "user", message_id: 100, message_index: 0, message: "创建技能" },
      { role: "assistant", message_id: 101, message_index: 1,
        message: [{ type: "summary", content: "第一版" }] },
      { role: "assistant", message_id: 102, message_index: 1,
        message: [{ type: "summary", content: "第二版" }] },
    ],
  } as ApiConversationDetail;
  const adapter = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  );
  const history = await adapter.load();
  expect(history.messages.map((item) => [item.message.id, item.parentId])).toEqual([
    ["100", null], ["101", "100"], ["102", "100"],
  ]);
  expect(history.headId).toBe("102");
});
