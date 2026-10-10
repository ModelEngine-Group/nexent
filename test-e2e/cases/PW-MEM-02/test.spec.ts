import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ResourcePage } from "../../infra/automation/d4/pages/resource.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const required = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const memoryTabNames = {
  base: /^(?:Base Settings|基础设置)$/,
  tenant: /^(?:Tenant|租户)$/,
  user: /^(?:User|用户)$/,
  agent: /^(?:Agent|智能体)(?:\s*\d+)?$/,
};

journey("PW-MEM-02", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MEM-02");
  const marker = `MEMORY-${token}`;
  let agent = "";
  let conversationId = 0;
  let originalSchedule: any;
  const chat = new ChatPage(page);
  const memoryRows = async () => {
    const response = await page.request.get("/api/memory/records?layer=agent&status=&limit=1000");
    expect(response.ok()).toBe(true);
    return (await response.json()).items || [];
  };
  const showRecords = async () => {
    await page.goto(appPath("/memory"));
    await page.getByRole("tab", { name: memoryTabNames.agent }).click();
    await page.getByPlaceholder(/搜索|Search/).fill(token);
  };
  const dreaming = () => page.locator(".memory-config-card").filter({ has: page.getByText("开启自动 Dreaming", { exact: true }) }).getByRole("switch");
  const restoreSchedule = async () => {
    if (!originalSchedule) return;
    const response = await page.request.put("/api/memory/dreaming/schedule", { data: originalSchedule });
    expect(response.ok()).toBe(true);
  };
  const setDreaming = async (enabled: boolean) => {
    await expect(dreaming()).toBeVisible();
    if (await dreaming().getAttribute("aria-checked") !== String(enabled)) {
      await dreaming().click();
      const saved = page.waitForResponse(r => r.url().includes("/memory/dreaming/schedule") && r.request().method() === "PUT");
      await page.getByRole("button", { name: "保存计划", exact: true }).click();
      expect((await saved).ok()).toBe(true);
    }
    await page.reload();
    await expect(dreaming()).toHaveAttribute("aria-checked", String(enabled));
  };
  contract.deferCleanup(async () => {
    try { await restoreSchedule(); } finally {
      if (conversationId) {
        for (const record of await memoryRows()) {
          if (String(record.conversation_id) === String(conversationId) && record.content.includes(marker)) {
            const removed = await page.request.delete(`/api/memory/records/${record.memory_id}`);
            expect(removed.ok()).toBe(true);
          }
        }
        await chat.deleteConversationById(conversationId);
      }
    }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { expect(configuredFeature("memory")).toBe(true); agent = resolveReadyAsset("agents", "d4_chat_display_name", "PW-MEM-02"); return `Memory is configured for READY Agent ${agent}`; },
      async () => `Agent ${agent} is the current batch's real-model asset`,
      async () => `fixed two-turn marker ${marker}; Dreaming configuration and conversation have finally cleanup`,
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await chat.openAgent(agent); await chat.sendAndWait(`请记住唯一标记 ${marker}。`); conversationId = chat.currentConversationId(); await chat.sendAndWait("重复你刚才记住的唯一标记。"); return `completed two-turn real conversation ${conversationId} without requiring sidebar rename`; },
      async () => { await expect(chat.assistantMessages().last()).toContainText(marker); await expect.poll(async () => (await memoryRows()).some((row: any) => String(row.conversation_id) === String(conversationId) && row.content.includes(marker)), { timeout: 180000, intervals: [2000, 5000] }).toBe(true); return "real asynchronous memory extraction produced this conversation's marker"; },
      async () => { await showRecords(); return "filtered Agent records by the unique marker"; },
      async () => { await expect(page.getByRole("row").filter({ hasText: marker }).first()).toBeVisible(); return "the UI exposes this conversation's memory record"; },
      async () => { await page.getByRole("tab", { name: memoryTabNames.base }).click(); const response = await page.request.get("/api/memory/dreaming/schedule"); expect(response.ok()).toBe(true); originalSchedule = await response.json(); await setDreaming(true); return "enabled automatic Dreaming, saved its plan and verified refresh persistence"; },
      async () => { await setDreaming(false); return "disabled and saved automatic Dreaming; this current UI retains history without a deletion dialog"; },
      async () => { await showRecords(); await expect(page.getByRole("row").filter({ hasText: marker }).first()).toBeVisible(); return "memory history remained after disabling Dreaming"; },
      async () => { await restoreSchedule(); await page.goto(appPath("/memory")); await expect(dreaming()).toHaveAttribute("aria-checked", String(originalSchedule.enabled)); return "restored and reloaded the original Dreaming schedule"; },
    ],
    assertions: [
      async () => { await showRecords(); await expect(page.getByRole("row").filter({ hasText: marker }).first()).toBeVisible(); return "real conversation created observable Agent memory"; },
      async () => { expect(typeof originalSchedule.enabled).toBe("boolean"); const response = await page.request.get("/api/memory/dreaming/schedule"); expect(response.ok()).toBe(true); expect((await response.json()).enabled).toBe(originalSchedule.enabled); return "Dreaming toggle persistence, retained history and original-state restoration verified"; },
      async () => "semantic recall quality is delegated to D3; this Journey asserted real extraction and UI state",
    ],
  });
});

