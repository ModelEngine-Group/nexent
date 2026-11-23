import { spawn } from "node:child_process";
import { join } from "node:path";

export async function a2aProbe(args: string[]): Promise<any> {
  const repo = process.env.NEXENT_REPO;
  const python = process.env.FIXED_TEST_PYTHON;
  if (!repo || !python) throw new Error("A2A probe requires the existing repository and interpreter configuration");
  return new Promise((resolve, reject) => {
    const child = spawn(python, [join(repo, "test-e2e/infra/automation/d4/a2a_client.py"), ...args], { env: process.env });
    let output = "";
    let errors = "";
    const timer = setTimeout(() => { child.kill(); reject(new Error("A2A probe exceeded its cleanup-aware deadline")); }, 660000);
    child.stdout.on("data", (data) => { output += data; });
    child.stderr.on("data", (data) => { errors += data; });
    child.on("error", (error) => { clearTimeout(timer); reject(error); });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        const error = new Error(`A2A external probe failed: ${errors.slice(-1000)}`);
        error.name = "ProductFailure";
        reject(error);
        return;
      }
      try { resolve(JSON.parse(output)); } catch { reject(new Error("A2A probe returned invalid JSON")); }
    });
  });
}
