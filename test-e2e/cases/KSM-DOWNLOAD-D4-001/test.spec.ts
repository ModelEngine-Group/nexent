// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { promisify } from "node:util";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { journey } from "../../infra/automation/d4/runner/journey";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";

const caseId = "KSM-DOWNLOAD-D4-001";
const execute = promisify(execFile);

async function fixture(operation: string, ...args: string[]) {
  const python = process.env.FIXED_TEST_PYTHON;
  const repo = process.env.NEXENT_REPO;
  if (!python || !repo) throw new Error("Runner interpreter and repository are required");
  try {
    const result = await execute(python, [join(repo, "test-e2e/infra/automation/d4/tool_fastpath_client.py"),
      operation, "--case-id", caseId, ...args], { timeout: 150000 });
    return JSON.parse(result.stdout);
  } catch (error) {
    // The bridge emits only a sanitized exception type on stderr.
    let diagnostic: { error_type?: string } = {};
    try { diagnostic = JSON.parse(String((error as { stderr?: string }).stderr || "")); } catch { /* No raw output. */ }
    const failure = new Error(`${caseId} ${operation} failed (${diagnostic.error_type || "BridgeError"})`);
    if (diagnostic.error_type === "AssetDependencyError") failure.name = "DependencyFailure";
    throw failure;
  }
}

journey(caseId, async (context) => {
  const { page, contract, expect } = context;
  const chat = new ChatPage(page);
  const prompt = "Use the controlled Python model to create and publish the test file.";
  let owned: { nonce: string; display: string; agent_id: number };
  let artifact: { filename: string; pod_uid: string; sha256: string };
  let conversation = 0;
  let digest = "";
  let recording: Promise<number> | undefined;
  contract.deferCleanup(async () => {
    try {
      await recording;
    } finally {
      await fixture("cleanup");
    }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        owned = await fixture("setup");
        await loginCurrent(page, "tenant_a_admin");
        return "Disposable Kubernetes SYSTEM deployment, browser identity and owned Agent ready";
      },
      async () => {
        await fixture("reset", "--promoted");
        return "Controlled provider queued Python and artifact delivery actions";
      },
    ],
    steps: [
      async () => {
        await chat.openAgent(owned.display);
        const mode = page.getByRole("button", { name: /^(规划|执行)模式$/ })
          .and(page.locator('[aria-haspopup="dialog"]'));
        await mode.click();
        await page.getByRole("dialog").getByRole("button", { name: "执行模式", exact: true }).click();
        recording = page.waitForResponse((response) => {
          const request = response.request();
          if (request.method() !== "POST" || !new URL(response.url()).pathname.endsWith("/api/agent/run")) {
            return false;
          }
          const body = request.postDataJSON();
          return body?.query === prompt && body?.agent_id === owned.agent_id;
        }).then(async (response) => {
          const id = Number((await response.allHeaders()).conversation_id || response.request().postDataJSON().conversation_id);
          expect(Number.isInteger(id) && id > 0).toBe(true);
          await fixture("record", "--promoted", "--conversation", String(id));
          expect(response.ok()).toBe(true);
          return id;
        });
        recording.catch(() => undefined); // Cleanup awaits and reports recording failures.
        await chat.startMessage(prompt);
        conversation = await recording;
        return `Submitted through browser for conversation ${conversation}`;
      },
      async () => {
        await chat.waitForCompletion();
        artifact = await fixture("inspect", "--promoted", "--conversation", String(conversation));
        expect(artifact.pod_uid).toBeTruthy();
        await expect(chat.assistantMessages().last()).toContainText(`KSM_DOWNLOAD_${owned.nonce}`);
        return `Result is persisted and scoped to sandbox Pod ${artifact.pod_uid}`;
      },
      async () => {
        const link = chat.assistantMessages().last().locator("a.aui-md-a").filter({ hasText: artifact.filename });
        await expect(link).toHaveCount(1);
        const event = page.waitForEvent("download");
        await link.click();
        const download = await event;
        expect(await download.failure()).toBeNull();
        expect(download.suggestedFilename()).toBe(artifact.filename);
        const stream = await download.createReadStream();
        if (!stream) throw new Error("Browser did not provide the downloaded file stream");
        const sha256 = createHash("sha256");
        for await (const chunk of stream) sha256.update(chunk);
        digest = sha256.digest("hex");
        expect(digest).toBe(artifact.sha256);
        return `Browser download SHA-256 ${digest}`;
      },
    ],
    assertions: [
      async () => {
        expect(digest).toBe(createHash("sha256").update("2\n4\n6\n", "utf8").digest("hex"));
        return "Browser downloaded the bytes produced by the Kubernetes run";
      },
    ],
  });
});
