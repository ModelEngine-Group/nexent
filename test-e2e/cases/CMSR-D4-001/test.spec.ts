import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const execute = promisify(execFile);
async function fixture(operation: string, args: string[] = []) {
  const python = process.env.FIXED_TEST_PYTHON;
  const repo = process.env.NEXENT_REPO;
  if (!python || !repo) throw new Error("Existing runner interpreter/repository configuration is required");
  try {
    const result = await execute(python, [join(repo, "test-e2e/infra/automation/d4/cmsr_client.py"), operation, ...args],
      { timeout: 60000, env: process.env });
    return JSON.parse(result.stdout);
  } catch (error) {
    // Python exceptions can contain auth request bodies; retain only safe diagnostics.
    let detail = "";
    try {
      const diagnostic = JSON.parse(String((error as { stderr?: string }).stderr || ""));
      if (/^[A-Za-z]+Error$/.test(diagnostic.error_type || "")) detail = diagnostic.error_type;
      if (diagnostic.error_type === "HistoryVerificationError" &&
          /^(failed_fragment_present|empty_code_present|committed_marker_present|final_marker_present|parse_count|step_count): expected (True|False|1|2), observed (True|False|\d+)$/.test(diagnostic.check || "")) {
        detail += `: ${diagnostic.check}`;
      }
    } catch { /* Unknown child output must not expose auth request bodies. */ }
    throw new Error(`CMSR fixture operation failed: ${operation}${detail ? ` (${detail})` : ""}; see runtime/cmsr-history.json`);
  }
}

journey("CMSR-D4-001", async (context) => {
  const { page, contract, expect } = context;
  const chat = new ChatPage(page);
  const owned: Array<{ nonce: string; conversation?: number }> = [];
  let current: { nonce: string; display: string; conversation?: number };
  const message = () => chat.assistantMessages().last();
  const expand = async () => {
    const collapsed = message().locator('.aui-reasoning-root button[data-state="closed"]');
    while (await collapsed.count()) await collapsed.first().click();
  };
  const state = () => fixture("state", ["--nonce", current.nonce]);
  const release = (phase: string) => fixture(phase, ["--nonce", current.nonce]);
  const start = async (mode: string) => {
    current = await fixture("setup");
    owned.push(current);
    await fixture("reset", ["--nonce", current.nonce, "--mode", mode]);
    await chat.openAgent(current.display);
    await chat.selectMode("执行");
    await chat.startMessage("Execute one code action and finish.");
    current.conversation = chat.currentConversationId();
    await expect.poll(async () => (await state()).paused, { timeout: 60000 }).toBe("failed");
    await expect(message().locator(".aui-reasoning-root").first()).toContainText(/Step\s*1|步骤\s*1/);
    await expand();
    if (mode === "transport") await expect(message()).toContainText(`CMSR_FAILED_${current.nonce}`);
    await release("failed");
    await expect.poll(async () => (await state()).paused, { timeout: 60000 }).toBe("success");
  };
  const paused = async () => {
    await expand();
    try {
      await expect(message()).toContainText(`CMSR_OK_${current.nonce}`);
    } catch {
      const observed = await state();
      const failure = new Error(`CMSR successful fragment missing in browser: mode fixture paused=${observed.paused}, calls=${observed.calls}, completed=${observed.completed}, expired=${observed.expired}; see runtime/cmsr-provider-state.json and failure.png`);
      if (observed.paused === 'success' && observed.calls === 2 && !observed.expired) failure.name = 'ProductFailure';
      throw failure;
    }
    await expect(message()).not.toContainText(`CMSR_FAILED_${current.nonce}`);
    await expect(message()).not.toContainText("<code></code>");
    await expect(message().locator(".aui-reasoning-root")).toHaveCount(1);
    expect((await state()).completed).toBe(false);
    expect((await state()).calls).toBe(2);
  };
  const complete = async () => {
    await release("success");
    await chat.waitForCompletion(60000);
    await expand();
    await expect(message()).toContainText(`CMSR_FINAL_${current.nonce}`);
    await expect(message().getByRole("button", { name: /Executed code/ })).toHaveCount(1);
    // Automatic titles can legitimately collide (including with the New Chat
    // action). Give only this owned conversation a stable unique lookup title.
    const title = `CMSR-${current.nonce}`;
    const renamed = await page.request.post("/api/conversation/rename", {
      data: { conversation_id: current.conversation, name: title },
    });
    expect(renamed.ok()).toBe(true);
    expect((await renamed.json()).code).toBe(0);
    expect((await fixture("history", ["--nonce", current.nonce, "--conversation", String(current.conversation)])).verified).toBe(true);
    await page.reload({ waitUntil: "domcontentloaded" });
    await chat.openThread(title);
    await expand();
    await expect(message().locator(".aui-reasoning-root")).toHaveCount(1);
    await expect(message()).toContainText(`CMSR_OK_${current.nonce}`);
    await expect(message().getByRole("button", { name: /Executed code/ })).toHaveCount(1);
    await expect(message()).not.toContainText(`CMSR_FAILED_${current.nonce}`);
    await expect(message()).not.toContainText(/Connecting/);
    expect((await state()).calls).toBe(3);
  };
  contract.deferCleanup(async () => {
    const errors: string[] = [];
    for (const item of owned) {
      try { await fixture("delete", ["--nonce", item.nonce]); } catch { errors.push("provider cleanup failed"); }
      if (item.conversation) {
        try { await chat.deleteConversationById(item.conversation); } catch { errors.push("conversation cleanup failed"); }
      }
    }
    if (errors.length) throw new Error(errors.join("; "));
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { await loginCurrent(page, "tenant_a_admin"); return "authenticated local Nexent browser"; },
      async () => "runner-owned model fixture and dynamically owned Agent use no global model replacement",
    ],
    steps: [
      async () => { await start("transport"); return "Step 1 and failed fragment observed; actual transport failure triggered"; },
      async () => { await paused(); return "successful raw content visible while provider completion remains gated"; },
      async () => { await complete(); return "single action persisted; refreshed reasoning is nonempty"; },
      async () => { await start("semantic"); await paused(); await complete(); return "step-one semantic repair streams and survives refresh"; },
    ],
    assertions: [
      async () => { await expect(message().locator(".aui-reasoning-root").first()).toContainText(/Step\s*1|步骤\s*1/); return "Step 1 retained"; },
      async () => { await expect(message()).toContainText(`CMSR_OK_${current.nonce}`); return "no terminal label-only reasoning"; },
      async () => { expect((await state()).completed).toBe(true); return "both sequences verified content before explicit provider release"; },
      async () => { expect((await fixture("history", ["--nonce", current.nonce, "--conversation", String(current.conversation)])).verified).toBe(true); return "persisted single action and committed text match the refreshed UI"; },
    ],
  });
});
