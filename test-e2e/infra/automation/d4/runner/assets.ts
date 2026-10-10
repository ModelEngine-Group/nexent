import { spawnSync } from "node:child_process";
import { join } from "node:path";

function invoke(args: string[]): string {
  const root = process.env.TEST_ROOT;
  if (!root) throw new Error("TEST_ROOT is required for the batch asset registry");
  const repo = process.env.NEXENT_REPO;
  if (!repo) throw new Error("NEXENT_REPO is required for the asset bridge");
  const result = spawnSync(process.env.FIXED_TEST_PYTHON || "python3", [join(repo, "test-e2e/infra/automation/d4/asset_bridge.py"), ...args], { encoding: "utf8", env: process.env });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout).trim();
    if (detail.includes("required test asset is not READY")) {
      const error = new Error(`asset registry command failed: ${detail}`) as Error & { dependencyCaseId?: string };
      error.name = "DependencyFailure";
      error.dependencyCaseId = detail.match(/dependency=([^;\s]+)/)?.[1] || "UNKNOWN_PRODUCER";
      throw error;
    }
    throw new Error(`asset registry command failed: ${detail}`);
  }
  const payload = JSON.parse(result.stdout);
  return String(payload.value);
}

export function registerReadyAsset(section: string, key: string, value: string, owner: string, cleanup?: object): void {
  const args = ["register", "--section", section, "--key", key, "--value", value, "--owner", owner];
  if (cleanup) args.push("--cleanup-json", JSON.stringify(cleanup));
  invoke(args);
}

export function resolveReadyAsset(section: string, key: string, consumer: string): string {
  return invoke(["resolve", "--section", section, "--key", key, "--consumer", consumer]);
}
