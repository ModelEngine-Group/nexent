import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { join } from "node:path";
import type { Locator, Response } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const execute = promisify(execFile);
async function fixture(operation: string, args: string[] = []) {
  const python = process.env.FIXED_TEST_PYTHON;
  const repo = process.env.NEXENT_REPO;
  if (!python || !repo) throw new Error("Runner interpreter and repository are required");
  try {
    const result = await execute(python, [join(repo, "test-e2e/infra/automation/d4/tool_fastpath_client.py"), operation, ...args],
      { timeout: operation === "cleanup" ? 300000 : 150000, env: process.env });
    return JSON.parse(result.stdout);
  } catch (error) {
    let type = "BridgeError";
    try {
      const diagnostic = JSON.parse(String((error as { stderr?: string }).stderr || ""));
      if (/^[A-Za-z]+Error$/.test(diagnostic.error_type || "")) type = diagnostic.error_type;
    } catch { /* Raw child output may contain authenticated request details. */ }
    const failure = new Error(`TFP ${operation} failed (${type}); inspect runtime/tfp-browser-history-*.json`);
    if (type === "AssetDependencyError") failure.name = "DependencyFailure";
    else if (type === "AssertionError") failure.name = "ProductFailure";
    throw failure;
  }
}

journey("TFP-D4-001", async (context) => {
  const { page, contract, expect } = context;
  const chat = new ChatPage(page);
  let owned: { nonce: string; display: string; agent_id: number };
  const completed: Array<{ conversation: number; promoted: boolean; title: string }> = [];
  const recordings: Promise<void>[] = [];
  let recordingError: unknown;
  let pending: { prompt: string; promoted: boolean } | undefined;
  const recordResponse = (response: Response) => {
    const request = response.request();
    if (!pending || request.method() !== "POST" || !new URL(response.url()).pathname.endsWith("/api/agent/run")) return;
    const body = request.postDataJSON();
    if (body?.query !== pending.prompt || body?.agent_id !== owned.agent_id) return;
    const promoted = pending.promoted;
    // Register the server ID as soon as the real run response arrives, even
    // when ChatPage's next DOM assertion fails or the stream is cancelled.
    recordings.push((async () => {
      const headers = await response.allHeaders();
      const conversation = Number(headers.conversation_id || body.conversation_id);
      expect(Number.isInteger(conversation) && conversation > 0).toBe(true);
      await fixture("record", ["--conversation", String(conversation), ...(promoted ? ["--promoted"] : [])]);
    })().catch((error) => { recordingError = error; }));
  };
  page.on("response", recordResponse);
  contract.deferCleanup(async () => {
    page.off("response", recordResponse);
    await Promise.all(recordings);
    await fixture("cleanup");
    if (recordingError) throw recordingError;
  });
  const expand = async (message: Locator) => {
    for (let count = 0; count < 30; count += 1) {
      const closed = message.locator('.aui-reasoning-root button[data-state="closed"]');
      if (!(await closed.count())) return;
      await closed.first().click();
    }
    throw new Error("Reasoning/tool expansion did not settle");
  };
  const visible = async (promoted: boolean) => {
    await expect(chat.userMessages()).toHaveCount(1);
    await expect(chat.assistantMessages()).toHaveCount(1);
    const message = chat.assistantMessages().last();
    await expand(message);
    await expect(message).toContainText(`TFP_${promoted ? "PROMOTED" : "FAST"}_${owned.nonce}`);
    await expect(message.getByRole("button", { name: "Used tool: read_skill_config", exact: true }))
      .toHaveCount(promoted ? 2 : 1);
    for (const name of ["run_skill_script", "upload_to_s3"]) {
      await expect(message.getByRole("button", { name: `Used tool: ${name}`, exact: true })).toHaveCount(promoted ? 1 : 0);
    }
    await expect(message.getByRole("button", { name: /Used tool:/ })).toHaveCount(promoted ? 4 : 1);
    await expect(message.getByRole("button", { name: /Executed code/ })).toHaveCount(promoted ? 3 : 1);
    await expect(message).not.toContainText(/Cancelled tool|LocalPythonExecutor|TFP_DOCKER_.*_False/);
  };
  const inspect = async (conversation: number, promoted: boolean) => {
    const result = await fixture("inspect", ["--conversation", String(conversation), ...(promoted ? ["--promoted"] : [])]);
    expect(result.verified).toBe(true);
    return result;
  };
  const download = async (artifact: { filename: string; expected_text: string }) => {
    const link = chat.assistantMessages().last().locator("a.aui-md-a")
      .filter({ hasText: artifact.filename });
    await expect(link).toHaveCount(1);
    const event = page.waitForEvent("download");
    await link.click();
    const file = await event;
    expect(await file.failure()).toBeNull();
    expect(file.suggestedFilename()).toBe(artifact.filename);
    const stream = await file.createReadStream();
    expect(stream).not.toBeNull();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks)).toEqual(Buffer.from(artifact.expected_text, "utf8"));
  };
  const run = async (promoted: boolean) => {
    await fixture("reset", promoted ? ["--promoted"] : []);
    if (promoted) await chat.newConversation(owned.display);
    else await chat.openAgent(owned.display);
    await chat.selectMode("执行");
    pending = { prompt: `Execute controlled TFP ${promoted ? "promotion" : "cold"} verification.`, promoted };
    await chat.startMessage(pending.prompt);
    await Promise.all(recordings);
    if (recordingError) throw recordingError;
    expect(recordings).toHaveLength(promoted ? 2 : 1);
    const conversation = chat.currentConversationId();
    await chat.waitForCompletion();
    await visible(promoted);
    const result = await inspect(conversation, promoted);
    if (promoted) await download(result.artifact);
    const title = `TFP-${owned.nonce}-${promoted ? "promoted" : "cold"}`;
    const renamed = await page.request.post("/api/conversation/rename", { data: { conversation_id: conversation, name: title } });
    expect(renamed.ok()).toBe(true);
    expect((await renamed.json()).code).toBe(0);
    completed.push({ conversation, promoted, title });
    pending = undefined;
    await page.reload({ waitUntil: "domcontentloaded" });
    await chat.openThread(title);
    await visible(promoted);
    const restored = await inspect(conversation, promoted);
    expect(restored).toEqual(result);
    if (promoted) await download(restored.artifact);
  };
  await executeFixedScenario(context, {
    preconditions: [
      async () => { owned = await fixture("setup"); return "running SDK fingerprints and private fixture verified"; },
      async () => { await loginCurrent(page, "tenant_a_admin"); return "disposable authenticated browser"; },
      async () => { expect(owned.agent_id).toBeGreaterThan(0); return "owned published Agent and controlled HTTP provider ready"; },
    ],
    steps: [
      async () => { await run(false); return "cold tool/JSON action, exact cards and persisted final verified"; },
      async () => { await run(true); return "Docker promotion, exact cards, reload and browser report bytes verified"; },
    ],
    assertions: [
      async () => {
        expect(completed.map((run) => run.promoted)).toEqual([false, true]);
        expect(new Set(completed.map((run) => run.conversation)).size).toBe(2);
        await visible(true);
        return "independent owned runs completed with no duplicated tool card";
      },
      async () => {
        const current = completed[1];
        const result = await inspect(current.conversation, true);
        await visible(true);
        await download(result.artifact);
        return "refreshed history and authenticated browser download retain exact migrated report bytes";
      },
    ],
  });
});
