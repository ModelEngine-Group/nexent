import fs from "node:fs";

export function getDevBundlerOptions(dev, nodeModulesPath) {
  if (!dev) return {};

  // Turbopack cannot follow a worktree's shared dependency link outside its root.
  const sharedDependencies =
    fs.existsSync(nodeModulesPath) &&
    fs.lstatSync(nodeModulesPath).isSymbolicLink();

  return sharedDependencies ? { webpack: true } : { turbo: true };
}
