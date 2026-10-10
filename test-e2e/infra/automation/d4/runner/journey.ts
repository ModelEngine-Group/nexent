import { test, expect, Page } from "playwright/test";
import { appendFileSync, existsSync, readFileSync, renameSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { spawnSync } from "node:child_process";

type CheckKind = "preconditions" | "steps" | "assertions";
type FinalResult = "PASS" | "FAIL" | "TIMEOUT" | "AUTOMATION_ERROR" | "BLOCKED" | "BLOCKED_BY_DEPENDENCY";
type QueueCheck = { id: string; text: string };
type QueueItem = {id: string; contract_hash: string; precondition_items: QueueCheck[]; step_items: QueueCheck[]; assertion_items: QueueCheck[]};
type EvidenceRow = { id: string; name: string; status: string; observed: string; evidence?: string[] };
type NetworkEvidence = { time: string; method: string; url: string; status?: number; resource_type: string; failure?: string };
type EvidenceFile = {
  schema_version: number; case_id: string; contract_hash: string; started_at: string; finished_at: string;
  status: string; preconditions: EvidenceRow[]; steps: EvidenceRow[]; assertions: EvidenceRow[];
  cleanup: { status: string; details: string }; console_errors: string[]; unexpected_5xx: string[]; notes: string;
};

const SECRET = /(authorization|cookie|token|api[-_ ]?key|password)\s*[:=]\s*[^\s,;]+/gi;

function redact(value: unknown): string {
  return String(value ?? "").replace(SECRET, "$1=[REDACTED]").slice(0, 4000);
}

function safeUrl(value: string): string {
  try {
    const parsed = new URL(value);
    parsed.search = "";
    parsed.hash = "";
    return redact(parsed.toString());
  } catch {
    return redact(value.split("?", 1)[0]);
  }
}

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`missing required environment variable ${name}`);
  return value;
}

function atomicJson(path: string, value: object): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.next`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  renameSync(temporary, path);
}

function control(args: string[]): void {
  const result = spawnSync(process.env.FIXED_TEST_PYTHON || "python3", [join(required("NEXENT_REPO"), "test-e2e/infra/automation/d4/control.py"), ...args], {encoding: "utf8", env: process.env});
  if (result.status !== 0) throw new Error(`d4 control failed: ${redact(result.stderr || result.stdout)}`);
}

function queueItem(caseId: string): QueueItem {
  const payload = JSON.parse(readFileSync(required("D4_QUEUE"), "utf8"));
  const matches = (payload.items || []).filter((item: QueueItem) => item.id === caseId);
  if (matches.length !== 1) throw new Error(`${caseId}: missing or duplicate queue contract`);
  return matches[0];
}

export class ContractExecution {
  private evidence: EvidenceFile;
  private currentKind: CheckKind | "" = "";
  private currentId = "";
  private cursors: Record<CheckKind, number> = { preconditions: 0, steps: 0, assertions: 0 };
  private cleanups: Array<() => Promise<void>> = [];
  readonly caseDir: string;
  readonly evidencePath: string;
  readonly eventsPath: string;
  readonly statusPath: string;

  constructor(readonly caseId: string, readonly item: QueueItem) {
    const resultDir = required("RESULT_DIR");
    this.caseDir = join(resultDir, "d4", caseId);
    this.evidencePath = join(this.caseDir, "assertions.json");
    this.eventsPath = join(this.caseDir, "events.jsonl");
    this.statusPath = join(this.caseDir, "status.json");
    mkdirSync(this.caseDir, { recursive: true });
    control(["scaffold", "--queue", required("D4_QUEUE"), "--result-dir", resultDir, "--case-id", caseId]);
    this.evidence = JSON.parse(readFileSync(this.evidencePath, "utf8"));
    this.status("RUNNING");
    this.event("CASE_STARTED", { contract_hash: item.contract_hash });
  }

  private event(event: string, details: object = {}): void {
    appendFileSync(this.eventsPath, `${JSON.stringify({ time: new Date().toISOString(), event, ...details })}\n`, "utf8");
  }

  private status(status: string, extra: object = {}): void {
    atomicJson(this.statusPath, {schema_version: 1, case_id: this.caseId, status, current_item_id: this.currentId, worker_pid: process.pid, last_activity_at: new Date().toISOString(), ...extra});
  }

  private list(kind: CheckKind): QueueCheck[] {
    return kind === "preconditions" ? this.item.precondition_items : kind === "steps" ? this.item.step_items : this.item.assertion_items;
  }

  expectedIds(kind: CheckKind): string[] {
    return this.list(kind).map((entry) => entry.id);
  }

  private persist(): void {
    this.evidence.finished_at = new Date().toISOString();
    atomicJson(this.evidencePath, this.evidence);
    this.status("RUNNING");
  }

  private async runItem(kind: CheckKind, id: string, action: () => Promise<unknown>): Promise<void> {
    const expected = this.list(kind)[this.cursors[kind]];
    if (!expected || expected.id !== id) throw new Error(`${this.caseId}: expected ${expected?.id || "end"}, got ${id}`);
    const row = this.evidence[kind].find((entry) => entry.id === id);
    if (!row) throw new Error(`${this.caseId}: evidence row ${id} is missing`);
    this.currentKind = kind;
    this.currentId = id;
    this.status("RUNNING");
    this.event("ITEM_STARTED", { kind, item_id: id });
    const heartbeat = setInterval(() => this.status("RUNNING"), Number(process.env.D4_HEARTBEAT_MS || "5000"));
    try {
      const observed = await action();
      row.status = "PASS";
      row.observed = redact(observed || "completed as specified");
      this.cursors[kind] += 1;
      this.event("ITEM_PASSED", { kind, item_id: id, observed: row.observed });
      this.persist();
    } catch (error) {
      row.status = "FAIL";
      row.observed = redact(error instanceof Error ? error.message : error);
      this.event("ITEM_FAILED", { kind, item_id: id, error: row.observed });
      this.persist();
      throw error;
    } finally {
      clearInterval(heartbeat);
    }
  }

  precondition(id: string, action: () => Promise<unknown>): Promise<void> { return this.runItem("preconditions", id, action); }
  step(id: string, action: () => Promise<unknown>): Promise<void> { return this.runItem("steps", id, action); }
  assertion(id: string, action: () => Promise<unknown>): Promise<void> { return this.runItem("assertions", id, action); }
  deferCleanup(action: () => Promise<void>): void { this.cleanups.push(action); }
  addConsoleError(value: string): void { this.evidence.console_errors.push(redact(value)); this.persist(); }
  addUnexpected5xx(value: string): void { this.evidence.unexpected_5xx.push(redact(value)); this.persist(); }

  async cleanup(): Promise<void> {
    const errors: string[] = [];
    for (const action of [...this.cleanups].reverse()) {
      try { await action(); } catch (error) { errors.push(redact(error)); }
    }
    this.evidence.cleanup = {status: errors.length ? "FAIL" : this.cleanups.length ? "PASS" : "NOT_REQUIRED", details: errors.join("; ")};
    this.persist();
    if (errors.length) {
      const error = new Error(`cleanup failed: ${errors.join("; ")}`);
      error.name = "CleanupError";
      throw error;
    }
  }

  complete(): void {
    for (const kind of ["preconditions", "steps", "assertions"] as CheckKind[]) {
      if (this.cursors[kind] !== this.list(kind).length) throw new Error(`${this.caseId}: ${kind} contract is incomplete`);
    }
    if (this.evidence.unexpected_5xx.length) throw new Error(`${this.caseId}: unexpected 5xx responses were recorded`);
  }

  failKind(error: unknown): FinalResult {
    const name = error instanceof Error ? error.name : "";
    if (/Cleanup/i.test(name)) return "AUTOMATION_ERROR";
    if (/DependencyFailure/i.test(name)) return "BLOCKED_BY_DEPENDENCY";
    if (/ProductFailure/i.test(name)) return "FAIL";
    if (/Timeout/i.test(name)) return "TIMEOUT";
    return this.currentKind === "assertions" ? "FAIL" : "AUTOMATION_ERROR";
  }

  finish(result: FinalResult, reason = ""): void {
    this.evidence.status = result === "PASS" ? "PASS" : result.startsWith("BLOCKED") ? "BLOCKED" : "FAIL";
    this.evidence.notes = redact(reason);
    this.evidence.finished_at = new Date().toISOString();
    atomicJson(this.evidencePath, this.evidence);
    this.status(result, { reason: redact(reason) });
    this.event("CASE_FINISHED", { result, reason: redact(reason) });
  }
}

export type JourneyContext = { page: Page; contract: ContractExecution; expect: typeof expect };

export function journey(caseId: string, body: (context: JourneyContext) => Promise<void>): void {
  test(caseId, async ({ page }) => {
    const started = Date.now();
    const contract = new ContractExecution(caseId, queueItem(caseId));
    const failurePng = join(contract.caseDir, "failure.png");
    const traceZip = join(contract.caseDir, "trace.zip");
    const failureJson = join(contract.caseDir, "failure.json");
    const networkJsonl = join(contract.caseDir, "failure-network.jsonl");
    const networkEvidence: NetworkEvidence[] = [];
    const evidence = [`d4/${caseId}/assertions.json`];
    let result: FinalResult = "PASS";
    let reason = "";
    let dependencyCaseId = "";
    await page.context().tracing.start({ screenshots: true, snapshots: true, sources: true });
    page.on("console", (message) => { if (message.type() === "error") contract.addConsoleError(message.text()); });
    page.on("response", (response) => {
      const request = response.request();
      networkEvidence.push({
        time: new Date().toISOString(), method: request.method(), url: safeUrl(response.url()),
        status: response.status(), resource_type: request.resourceType(),
      });
      if (response.status() >= 500) contract.addUnexpected5xx(`${response.status()} ${safeUrl(response.url())}`);
    });
    page.on("requestfailed", (request) => {
      networkEvidence.push({
        time: new Date().toISOString(), method: request.method(), url: safeUrl(request.url()),
        resource_type: request.resourceType(), failure: redact(request.failure()?.errorText || "request failed"),
      });
    });
    try {
      await body({ page, contract, expect });
      contract.complete();
      await contract.cleanup();
      await page.context().tracing.stop();
      contract.finish("PASS");
    } catch (error) {
      result = contract.failKind(error);
      dependencyCaseId = String((error as { dependencyCaseId?: string })?.dependencyCaseId || "");
      reason = redact(error instanceof Error ? `${error.name}: ${error.message}` : error);
      atomicJson(failureJson, {schema_version: 1, case_id: caseId, result, reason, occurred_at: new Date().toISOString()});
      evidence.push(relative(required("RESULT_DIR"), failureJson).replaceAll("\\", "/"));
      writeFileSync(networkJsonl, networkEvidence.map((row) => JSON.stringify(row)).join("\n") + (networkEvidence.length ? "\n" : ""), "utf8");
      evidence.push(relative(required("RESULT_DIR"), networkJsonl).replaceAll("\\", "/"));
      // Configuration/asset/contract failures can happen while the page is
      // still about:blank. A pure-white image is misleading evidence, so only
      // capture a screenshot after a product page has actually been opened.
      const productPageWasOpened = page.url() !== "about:blank";
      if (productPageWasOpened) {
        try {
          await page.screenshot({ path: failurePng, fullPage: true });
          evidence.push(relative(required("RESULT_DIR"), failurePng).replaceAll("\\", "/"));
        } catch { /* browser may be unavailable */ }
      }
      // Capture the failing UI before cleanup can navigate or delete its data.
      try { await contract.cleanup(); } catch { /* cleanup details are retained */ }
      try {
        await page.context().tracing.stop({ path: traceZip });
        if (existsSync(traceZip)) evidence.push(relative(required("RESULT_DIR"), traceZip).replaceAll("\\", "/"));
      } catch { /* retain any evidence already written */ }
      if ((result === "FAIL" || result === "TIMEOUT") && productPageWasOpened && (!existsSync(failurePng) || !existsSync(traceZip))) {
        result = "AUTOMATION_ERROR";
        reason = `browser evidence unavailable after failure: ${reason}`;
      }
      atomicJson(failureJson, {schema_version: 1, case_id: caseId, result, reason, occurred_at: new Date().toISOString()});
      contract.finish(result, reason);
    }
    const recordArgs = ["record", "--queue", required("D4_QUEUE"), "--results", required("D4_RESULTS"), "--result-dir", required("RESULT_DIR"), "--case-id", caseId, "--result", result, "--duration", String((Date.now() - started) / 1000), "--analysis", result === "PASS" ? "fixed Playwright contract completed" : reason];
    if (result !== "PASS") recordArgs.push("--reason", reason || result);
    if (result === "BLOCKED_BY_DEPENDENCY") recordArgs.push("--dependency-case-id", dependencyCaseId || "UNKNOWN_PRODUCER");
    for (const path of evidence) recordArgs.push("--evidence", path);
    control(recordArgs);
    if (result !== "PASS") throw new Error(`${caseId}: ${result}: ${reason}`);
  });
}
