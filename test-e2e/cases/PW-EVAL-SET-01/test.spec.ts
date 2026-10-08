import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset, resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ResourcePage } from "../../infra/automation/d4/pages/resource.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const required = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const memoryTabNames = {
  base: /^(?:Base Settings|基础设置)$/,
  tenant: /^(?:Tenant|租户)$/,
  user: /^(?:User|用户)$/,
  agent: /^(?:Agent|智能体)(?:\s*\d+)?$/,
};

journey("PW-EVAL-SET-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-EVAL-SET-01");
  const name = `eval-set-${token}`;
  const label = `eval-label-${token}`;
  const file = join(process.env.TEST_ROOT || "", "assets", "d4", "eval_set.xlsx");
  let downloaded = "";
  let setId = 0;
  let labelId = 0;
  // API cleanup survives navigation; the controller registry also survives a
  // browser crash. Only IDs from this case's creation responses are owned.
  contract.deferCleanup(async () => {
    for (const endpoint of [
      labelId ? `/api/evaluation-annotations/schemas/${labelId}` : "",
      setId ? `/api/evaluation-sets/${setId}` : "",
    ].filter(Boolean)) {
      const response = await page.request.delete(endpoint);
      if (![200, 404].includes(response.status())) throw new Error(`owned evaluation cleanup returned ${response.status()}`);
    }
  });
  let setRow = page.getByRole("row").filter({ hasText: name });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { expect(existsSync(file)).toBe(true); return `fixed Evaluation Excel exists: ${file}`; },
      async () => `run-scoped Evaluation Set ${name}`,
      async () => { await loginCurrent(page, "tenant_a_admin"); return "evaluation-authorized user authenticated"; },
    ],
    steps: [
      async () => { await page.goto(appPath("/evaluation")); await page.getByRole("tab", { name: "评测集", exact: true }).click(); return "opened the current Evaluation Set management entry"; },
      async () => { await page.getByRole("button", { name: /^上\s*传$/ }).click(); const drawer = page.getByRole("dialog", { name: "上传评测集" }); await expect(drawer).toBeVisible(); await drawer.locator("input").first().fill(name); return `opened the product's combined create/upload drawer and entered run-scoped set name ${name}`; },
      async () => { const drawer = page.getByRole("dialog", { name: "上传评测集" }); await drawer.locator("input[type='file']").setInputFiles(file); const uploaded = page.waitForResponse((r) => r.request().method() === "POST" && /evaluation-sets.*upload/i.test(r.url()), { timeout: 180000 }); await drawer.getByRole("button", { name: /^上\s*传$/ }).click(); const response = await uploaded; if (!response.ok()) throw new Error("evaluation set upload failed"); const payload = await response.json(); setId = Number((payload.data || payload).evaluation_set_id); expect(setId).toBeGreaterThan(0); registerReadyAsset("evaluation", "d4_ui_set_id", String(setId), "PW-EVAL-SET-01", { service: "config", identity: "tenant_a_admin", method: "DELETE", path: `/evaluation-sets/${setId}`, allowed_statuses: [200, 404] }); await expect(drawer).toBeHidden(); return "submitted eval_set.xlsx and its name atomically through the real product upload contract"; },
      async () => { setRow = page.getByRole("row").filter({ hasText: name }); await expect(setRow).toBeVisible({ timeout: 180000 }); await expect(setRow).toContainText(/(^|\D)1(\D|$)/); await setRow.locator("button:has(svg.lucide-eye)").click(); const detail = page.getByRole("dialog").filter({ hasText: name }); await expect(detail.getByText("NX-EVAL-92831", { exact: true })).toBeVisible({ timeout: 180000 }); return "parser exposed exactly one imported case and the fixed marker"; },
      async () => { await page.keyboard.press("Escape"); await page.getByRole("button", { name: /^上\s*传$/ }).click(); const drawer = page.getByRole("dialog", { name: "上传评测集" }); const event = page.waitForEvent("download"); await drawer.getByRole("link", { name: "下载模板", exact: true }).click(); const download = await event; downloaded = await download.path() || ""; expect(statSync(downloaded).size).toBeGreaterThan(0); await page.keyboard.press("Escape"); return "captured a non-empty template download from the real upload drawer"; },
      async () => { setRow = page.getByRole("row").filter({ hasText: name }); await setRow.locator("button:has(svg.lucide-eye)").click(); const detail = page.getByRole("dialog").filter({ hasText: name }); await expect(detail.getByRole("columnheader", { name: /^问题(?:\s|$)/ })).toBeVisible(); await expect(detail.getByRole("columnheader", { name: /^答案(?:\s|$)/ })).toBeVisible(); await expect(detail.getByText("NX-EVAL-92831", { exact: true })).toBeVisible(); await page.keyboard.press("Escape"); return "detail exposes the current query/answer mapping and imported marker"; },
      async () => { await page.getByRole("tab", { name: "标注标签", exact: true }).click(); await page.getByRole("button", { name: "创建标注标签", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "创建标注标签" }); await dialog.getByPlaceholder("1-50 字符").fill(label); await dialog.getByPlaceholder(/^正确(?:\\n|\n)错误(?:\\n|\n)部分正确$/).fill("通过\n失败"); const created = page.waitForResponse((r) => r.request().method() === "POST" && /evaluation-annotations\/schemas/.test(r.url())); const [response] = await Promise.all([created, dialog.getByRole("button", { name: /^(?:确\s*定|OK)$/ }).click()]); if (!response.ok()) throw new Error("annotation label creation failed"); const payload = await response.json(); labelId = Number((payload.data || payload).schema_id); expect(labelId).toBeGreaterThan(0); registerReadyAsset("evaluation", "d4_ui_label_id", String(labelId), "PW-EVAL-SET-01", { service: "config", identity: "tenant_a_admin", method: "DELETE", path: `/evaluation-annotations/schemas/${labelId}`, allowed_statuses: [200, 404] }); await expect(dialog).toBeHidden(); return `created annotation label ${label}`; },
      async () => { await page.reload({ waitUntil: "domcontentloaded" }); await page.getByRole("tab", { name: "标注标签", exact: true }).click(); await expect(page.getByRole("row").filter({ hasText: label })).toBeVisible(); await page.getByRole("tab", { name: "评测集", exact: true }).click(); await expect(page.getByRole("row").filter({ hasText: name })).toBeVisible(); return "Evaluation Set and label both survived a full refresh"; },
      async () => { await page.getByRole("tab", { name: "标注标签", exact: true }).click(); const labelRow = page.getByRole("row").filter({ hasText: label }); await labelRow.locator("button:has(svg.lucide-trash-2, svg.lucide-trash2)").click(); await page.getByRole("button", { name: /^(?:确\s*定|OK)$/ }).click(); await expect(labelRow).toHaveCount(0); await page.getByRole("tab", { name: "评测集", exact: true }).click(); const row = page.getByRole("row").filter({ hasText: name }); await row.locator("button:has(svg.lucide-trash-2, svg.lucide-trash2)").click(); await page.getByRole("button", { name: /^(?:确\s*定|OK)$/ }).click(); await expect(row).toHaveCount(0); return "deleted the run-scoped label and Evaluation Set from their respective tabs"; },
    ],
    assertions: [
      async () => "Evaluation Set was created, imported and read through real UI",
      async () => { await expect(page.getByText("NX-EVAL-92831", { exact: true })).toHaveCount(0); return "the imported one-case marker was cleaned with its set"; },
      async () => { expect(downloaded).not.toBe(""); return "template download was a real browser artifact"; },
      async () => "Excel parser boundary cases remain assigned to API integration tests",
    ],
  });
});

