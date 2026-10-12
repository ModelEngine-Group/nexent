import { readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { testUser } from "../../infra/automation/d4/runner/runtime-config";

journey("TPC-D4-001", async (context) => {
  const { page, expect } = context;
  const credentialPath = process.env.NEXENT_TEST_CREDENTIALS;
  if (!credentialPath) throw new Error("TPC deployed fixture configuration is required");
  const cfg = JSON.parse(readFileSync(credentialPath, "utf8"));
  const title = `TPC browser migration ${Date.now()}`;
  const warning = () => page.getByRole("dialog", { name: "Embedding model not configured", exact: true });
  const dismissWarning = async () => {
    await expect(warning()).toBeVisible();
    for (let attempt = 0; attempt < 3; attempt++) {
      if (!(await warning().isVisible())) return;
      await warning().getByRole("button", { name: "Close", exact: true }).click();
      try { await expect(warning()).toBeHidden({ timeout: 3000 }); return; }
      catch { if (attempt === 2) throw new Error("Embedding warning did not close"); }
    }
  };
  const code = () => page.getByRole("button", { name: "Executed code python", exact: true });
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        const user = testUser("tenant_a_dev");
        await page.goto("/en");
        await page.getByRole("button", { name: "Login Now", exact: true }).click();
        await page.getByPlaceholder("your@email.com").fill(user.username);
        await page.getByPlaceholder("Please enter your password").fill(user.password);
        await page.getByRole("button", { name: "Login", exact: true }).click();
        await expect(page.getByRole("button", { name: "Start Chatting", exact: true })).toBeVisible();
        const controlled = await page.request.post(`${cfg.provider}/__control`, { data: {
          responses: ['</think><code>skill_content = read_skill_md(skill_name="tpc-quality-check")\nprint(skill_content)</code>',
            "</think><final_answer>TPC_SKILL_READ_OK</final_answer>"], auxiliary_title: title,
        } });
        expect(controlled.ok()).toBe(true);
        await page.goto("/en/newchat");
        await expect(page.getByRole("button", { name: "PR4060 Repair Acceptance Controlled semantic repair verification", exact: true })).toBeVisible();
        return "authenticated test tenant and controlled provider ready";
      },
      async () => { await dismissWarning(); return "memory warning dismissed without changing settings"; },
    ],
    steps: [
      async () => {
        await page.getByRole("button", { name: "PR4060 Repair Acceptance Controlled semantic repair verification", exact: true }).click();
        await page.getByRole("textbox", { name: "Send a message...", exact: true }).fill("Read tpc-quality-check and reply with exactly TPC_SKILL_READ_OK");
        await page.getByRole("button", { name: "Send", exact: true }).click();
        await expect(code()).toBeVisible({ timeout: 60000 });
        await expect(page.getByRole("button", { name: "Stop generating", exact: true })).toBeHidden({ timeout: 60000 });
        await expect(page.getByText("TPC_SKILL_READ_OK", { exact: true })).toBeVisible();
        return "skill action executed and explicit final displayed";
      },
      async () => {
        await page.reload();
        await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible();
        await dismissWarning();
        await page.getByRole("button", { name: title, exact: true }).click();
        await expect(code()).toBeVisible();
        if ((await code().getAttribute("aria-expanded")) !== "true") await code().click();
        for (const group of await page.getByRole("button", { name: "1 tool call", exact: true }).all()) {
          if ((await group.getAttribute("aria-expanded")) !== "true") await group.click();
        }
        const skill = page.getByRole("button", { name: "Used tool: read_skill_md", exact: true });
        await expect(skill).toBeVisible();
        if ((await skill.getAttribute("aria-expanded")) !== "true") await skill.click();
        return "reopened saved conversation with expanded skill evidence";
      },
    ],
    assertions: [
      async () => {
        await expect(page.locator("body")).toContainText('"skill_name": "tpc-quality-check"');
        await expect(page.locator("body")).toContainText("TPC_REAL_SKILL_CONTENT");
        await expect(page.getByText("TPC_SKILL_READ_OK", { exact: true })).toBeVisible();
        await expect(code()).toHaveCount(1);
        await expect(page.getByRole("button", { name: "Used tool: read_skill_md", exact: true })).toHaveCount(1);
        await expect(page.locator("body")).not.toContainText("Connecting");
        await expect(page.locator("body")).not.toContainText("Thinking...");
        return "single persisted skill result and validated final; no pending or raw-action final";
      },
    ],
  });
});
