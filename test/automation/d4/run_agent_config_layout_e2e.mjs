import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../");
const result = spawnSync(process.execPath, [
  path.join(repositoryRoot, "frontend/node_modules/@playwright/test/cli.js"),
  "test", "--config", path.join(repositoryRoot, "test/automation/d4/agent-config.playwright.config.mjs"),
  "--grep", "AGENT-CONFIG-D4-001",
], { cwd: repositoryRoot, env: process.env, stdio: "inherit" });

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
