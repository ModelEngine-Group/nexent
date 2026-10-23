import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../"
);
const frontendRoot = path.join(repositoryRoot, "frontend");
const vitestCli = path.join(
  frontendRoot,
  "node_modules",
  "vitest",
  "vitest.mjs"
);
const result = spawnSync(
  process.execPath,
  [
    vitestCli,
    "run",
    "--config",
    path.join(repositoryRoot, "test/automation/d1/agent-config.vitest.config.mjs"),
    ...(process.argv[2] ? ["--testNamePattern", process.argv[2]] : []),
  ],
  { cwd: frontendRoot, stdio: "inherit" }
);

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
