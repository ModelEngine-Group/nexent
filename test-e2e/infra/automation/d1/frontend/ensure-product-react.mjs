import { existsSync, lstatSync, readlinkSync, rmSync, symlinkSync } from "node:fs";
import path from "node:path";

const repo = process.env.NEXENT_REPO;
const productModules = process.env.NEXENT_TEST_FRONTEND_MODULES ||
  (repo && path.join(repo, "frontend", "node_modules"));
if (!productModules) throw new Error("Configure NEXENT_REPO or NEXENT_TEST_FRONTEND_MODULES");
const localModules = path.resolve("node_modules");

for (const name of ["react", "react-dom"]) {
  const source = path.resolve(productModules, name);
  const target = path.join(localModules, name);
  if (!existsSync(source)) {
    throw new Error(`product dependency is missing: ${source}`);
  }
  if (existsSync(target) || lstatSafe(target)) {
    if (lstatSafe(target)?.isSymbolicLink() && readlinkSync(target) === source) continue;
    rmSync(target, { recursive: true, force: true });
  }
  symlinkSync(source, target, process.platform === "win32" ? "junction" : "dir");
}

function lstatSafe(target) {
  try {
    return lstatSync(target);
  } catch {
    return undefined;
  }
}
