import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export type TestUser = { id: string; username: string; password: string };

export function testUser(id: string): TestUser {
  const home = process.env.NEXENT_TEST_HOME || process.env.TEST_ROOT;
  const repo = process.env.NEXENT_REPO;
  const python = process.env.FIXED_TEST_PYTHON;
  if (!home || !repo || !python) throw new Error("test user configuration requires test home, repository and FIXED_TEST_PYTHON");
  // Use the shared YAML loader; only non-secret identity metadata crosses stdout.
  const result = spawnSync(python, [join(repo, "test-e2e/infra/automation/d4/user_config.py"), id], {
    encoding: "utf8", timeout: 10000, env: { ...process.env, NEXENT_TEST_HOME: home },
  });
  if (result.error || result.status !== 0) throw new Error(`config/users.yaml cannot resolve test user ${id}`);
  const configured = JSON.parse(result.stdout) as { username: string; password_env_key: string };
  const password = process.env[configured.password_env_key];
  if (!password) throw new Error(`configured password environment variable is missing for ${id}`);
  return { id, username: configured.username, password };
}

export function appPath(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return normalized.startsWith("/zh/") || normalized === "/zh" ? normalized : `/zh${normalized}`;
}

export function runToken(caseId: string, length = 10): string {
  const seed = `${process.env.RESULT_DIR || "local"}:${caseId}`;
  return createHash("sha256").update(seed).digest("hex").slice(0, length);
}

export function configuredFeature(name: string): boolean {
  const root = process.env.TEST_ROOT;
  if (!root) throw new Error("TEST_ROOT is required to read configured feature flags");
  const source = readFileSync(join(root, "config/environment.yaml"), "utf8");
  // JSON is a valid YAML representation used by the local setup writer.
  if (source.trimStart().startsWith("{")) {
    const value = JSON.parse(source).features?.[name];
    if (typeof value !== "boolean") throw new Error(`features.${name} must be a boolean in config/environment.yaml`);
    return value;
  }
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = source.match(new RegExp(`^\\s{2}${escaped}:\\s*(true|false)\\s*$`, "m"));
  if (!match) throw new Error(`features.${name} is missing from config/environment.yaml`);
  return match[1] === "true";
}

export type ModelAsset = { capability: string; provider: string; baseUrl: string; model: string; displayName: string; candidates: string[]; dimension?: number; secret: string };

export function configuredModel(capability: string): ModelAsset {
  const root = process.env.TEST_ROOT;
  if (!root) throw new Error("TEST_ROOT is required to read model configuration");
  const source = readFileSync(join(root, "config/models.yaml"), "utf8");
  const blocks = source.split(/^\s*-\s+id:\s*/m).slice(1);
  for (const block of blocks) {
    const read = (key: string): string => {
      // YAML permits an indentless sequence under `models:`. Accept any
      // horizontal indentation inside a model item; `\\s{4}` both assumed
      // the older four-space layout and could consume line breaks.
      const match = block.match(new RegExp(`^[ \\t]+${key}:[ \\t]*(?:\"([^\"]*)\"|'([^']*)'|([^\\r\\n#]+))`, "m"));
      return String(match?.[1] ?? match?.[2] ?? match?.[3] ?? "").trim();
    };
    if (read("capability") !== capability) continue;
    const secretKey = read("secret_env_key");
    const secret = process.env[secretKey] || "";
    if (!secret) throw new Error(`${capability} model secret ${secretKey} is unavailable`);
    const candidates = read("model").split(",").map((value) => value.trim()).filter(Boolean);
    const model = read("preferred_model") || candidates[0] || "";
    const baseUrl = read("base_url");
    if (!model || !baseUrl) throw new Error(`${capability} model config is incomplete`);
    if (!candidates.includes(model)) throw new Error(`${capability} preferred_model ${model} is not listed in model candidates`);
    const dimensionText = read("dimension");
    return { capability, provider: read("provider"), baseUrl, model, displayName: model, candidates, dimension: dimensionText ? Number(dimensionText) : undefined, secret };
  }
  throw new Error(`models.yaml does not define capability ${capability}`);
}

export function testAssetPath(relativePath: string): string {
  const root = process.env.TEST_ROOT;
  if (!root) throw new Error("TEST_ROOT is required to resolve test assets");
  return join(root, ...relativePath.split("/"));
}
