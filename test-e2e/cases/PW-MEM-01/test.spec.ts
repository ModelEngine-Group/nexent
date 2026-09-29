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

journey("PW-MEM-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MEM-01");
  const marker = `MEM-${token}`;
  const baseControl = () => page.locator(".memory-config-card").filter({ has: page.getByText("记忆能力", { exact: true }) }).getByRole("switch");
  let originalBase = "";
  let original: any = undefined;
  let firstVersion = 0;
  let changed = false;
  const active = async () => {
    const response = await page.request.get("/api/memory/long-term/user");
    expect(response.ok()).toBe(true);
    return (await response.json()).version;
  };
  const restoreContent = async () => {
    if (!changed) return;
    const current = await active();
    const response = original
      ? await page.request.post(`/api/memory/long-term/user/versions/${original.version_id}/activate`, { data: { expected_active_version_id: current?.version_id ?? null } })
      : await page.request.post("/api/memory/long-term/user/versions", { data: { content: "", expected_active_version_id: current?.version_id ?? null } });
    expect(response.ok()).toBe(true);
    expect((await active())?.content ?? "").toBe(original?.content ?? "");
    changed = false;
  };
  const restoreBase = async () => {
    if (!originalBase) return;
    await page.goto(appPath("/memory"));
    await page.getByRole("tab", { name: memoryTabNames.base }).click();
    const control = baseControl();
    await expect(control).toBeVisible();
    if (await control.getAttribute("aria-checked") !== originalBase) {
      const saved = page.waitForResponse(r => r.url().includes("/memory/config/") && r.request().method() !== "GET");
      await control.click();
      expect((await saved).ok()).toBe(true);
    }
  };
  contract.deferCleanup(async () => { try { await restoreContent(); } finally { await restoreBase(); } });
  const save = async (content: string) => {
    await page.getByRole("button", { name: /^编\s*辑$/ }).click();
    await page.getByRole("textbox", { name: "Markdown 记忆编辑器", exact: true }).fill(content);
    const saved = page.waitForResponse(r => r.url().endsWith("/memory/long-term/user/versions") && r.request().method() === "POST");
    changed = true;
    await page.getByRole("button", { name: /^保\s*存$/ }).click();
    expect((await saved).status()).toBe(201);
    await expect.poll(async () => (await active())?.content).toBe(content);
    await expect(page.getByRole("textbox", { name: "Markdown 记忆编辑器", exact: true })).toHaveValue(content);
  };
  await executeFixedScenario(context, {
    preconditions: [
      async () => { expect(configuredFeature("memory")).toBe(true); return "Memory feature is configured"; },
      async () => { await loginCurrent(page, "tenant_a_admin"); return "authorized administrator authenticated"; },
      async () => `run-scoped user-memory marker ${marker}; original active content is restored in finally`,
    ],
    steps: [
      async () => { await page.goto(appPath("/memory")); for (const name of Object.values(memoryTabNames)) await expect(page.getByRole("tab", { name })).toBeVisible(); return "Base/Tenant/User/Agent tabs are visible, including Agent count"; },
      async () => { const control = baseControl(); await expect(control).toBeVisible(); const initial = await page.request.get("/api/memory/config/load"); expect(initial.ok()).toBe(true); originalBase = String((await initial.json()).MEMORY_SWITCH === "Y"); await expect(control).toHaveAttribute("aria-checked", originalBase); const saved = page.waitForResponse(r => r.url().includes("/memory/config/") && r.request().method() !== "GET"); await control.click(); expect((await saved).ok()).toBe(true); await page.reload(); await expect(baseControl()).toHaveAttribute("aria-checked", originalBase === "true" ? "false" : "true"); await restoreBase(); return "Base toggle autosaved and survived refresh, then original value was restored"; },
      async () => { await page.getByRole("tab", { name: memoryTabNames.user }).click(); original = await active(); await expect(page.getByRole("button", { name: /^编\s*辑$/ })).toBeVisible(); return "opened versioned User long-term memory and captured the original active version"; },
      async () => { await save(marker); firstVersion = (await active()).version_id; return "saved a run-scoped Markdown memory version"; },
      async () => { await page.reload(); await page.getByRole("tab", { name: memoryTabNames.user }).click(); await expect(page.getByText(marker, { exact: true })).toBeVisible(); return "saved content survived refresh"; },
      async () => { await save(`${marker}-edited`); expect((await active()).content).toBe(`${marker}-edited`); return "edited content creates and activates a second persisted version"; },
      async () => { await page.getByRole("combobox").click(); const response = await page.request.get(`/api/memory/long-term/user/versions/${firstVersion}`); expect(response.ok()).toBe(true); const version = await response.json(); await page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter({ hasText: new RegExp(`^V${version.version_no} \\u00b7`) }).click(); await expect(page.getByText(marker, { exact: true })).toBeVisible(); await page.getByRole("button", { name: /^激\s*活$/ }).click(); const confirmed = page.waitForResponse(r => r.url().endsWith(`/versions/${firstVersion}/activate`) && r.request().method() === "POST"); await page.getByRole("dialog").getByRole("button", { name: /^确\s*[认定]$/ }).click(); expect((await confirmed).ok()).toBe(true); expect((await active()).version_id).toBe(firstVersion); return "selected the prior version in history, previewed its content and activated it through UI"; },
      async () => { await restoreContent(); return "restored original active content; immutable manual history is retained as product audit history"; },
      async () => { await restoreBase(); await page.reload(); await expect(baseControl()).toHaveAttribute("aria-checked", originalBase); return "original Base setting persists after final refresh"; },
    ],
    assertions: [
      async () => { for (const name of Object.values(memoryTabNames)) await expect(page.getByRole("tab", { name })).toBeVisible(); return "current tab structure and versioned long-term workflow are verified"; },
      async () => { expect(firstVersion).toBeGreaterThan(0); expect((await active())?.content ?? "").toBe(original?.content ?? ""); return "versions persisted and the original active content was restored"; },
      async () => { const other = await loginIsolated(page, "tenant_b_admin"); try { const response = await other.page.request.get("/api/memory/long-term/user"); expect(response.ok()).toBe(true); expect(JSON.stringify(await response.json())).not.toContain(marker); const hidden = await other.page.request.get(`/api/memory/long-term/user/versions/${firstVersion}`); expect(hidden.status()).toBe(404); } finally { await other.context.close(); } return "another tenant cannot read this user's run-scoped version"; },
    ],
  });
});

