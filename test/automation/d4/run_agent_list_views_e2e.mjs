import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../"
);
const frontendRoot = path.join(repositoryRoot, "frontend");
const playwrightCli = path.join(
  frontendRoot,
  "node_modules",
  "@playwright",
  "test",
  "cli.js"
);
const result = spawnSync(
  process.execPath,
  [playwrightCli, "test", "e2e/agent-list-high-fidelity.spec.ts"],
  { cwd: frontendRoot, env: process.env, stdio: "inherit" }
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
