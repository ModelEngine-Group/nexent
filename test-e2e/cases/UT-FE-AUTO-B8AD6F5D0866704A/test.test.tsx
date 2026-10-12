import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const NEXENT_REPO = process.env.NEXENT_REPO;
if (!NEXENT_REPO) {
  throw new Error("NEXENT_REPO must point to the local Nexent checkout");
}
const PRODUCT_FRONTEND = path.join(NEXENT_REPO, "frontend");

const BUILD_CONFIG = path.join(PRODUCT_FRONTEND, "build-config.js");
const BUILT_IN_LOCALES_DIR = path.join(PRODUCT_FRONTEND, "public", "locales");
const BUILT_IN_ZH_CUSTOM = path.join(BUILT_IN_LOCALES_DIR, "zh", "custom.json");

type BuildConfigModule = {
  ensureDir: (dir: string) => void;
  readLocaleConfig: (lang: string) => Record<string, unknown>;
  saveLocaleConfig: (fileData: string, lang: string) => string;
};

const tmpDirs: string[] = [];

function makeTmpDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "nexent-bcfg-"));
  tmpDirs.push(dir);
  return dir;
}

function listJsonFiles(dir: string): string[] {
  const result: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      result.push(...listJsonFiles(full));
    } else if (entry.name.endsWith(".json")) {
      result.push(full);
    }
  }
  return result;
}

function snapshotBuiltInLocales(): Record<string, string> {
  const snapshot: Record<string, string> = {};
  for (const file of listJsonFiles(BUILT_IN_LOCALES_DIR)) {
    snapshot[path.relative(BUILT_IN_LOCALES_DIR, file)] = fs.readFileSync(file, "utf-8");
  }
  return snapshot;
}

const builtInBefore = snapshotBuiltInLocales();

function runBuildConfig(
  limit: string | undefined,
  projectConfigDir: string
): { status: number | null; stderr: string } {
  const env: NodeJS.ProcessEnv = { ...process.env, PROJECT_CONFIG_DIR: projectConfigDir };
  if (limit === undefined) {
    delete env.FILE_UPLOAD_SIZE_LIMIT;
  } else {
    env.FILE_UPLOAD_SIZE_LIMIT = limit;
  }
  const res = spawnSync(process.execPath, [BUILD_CONFIG], { env, encoding: "utf-8" });
  return { status: res.status, stderr: String(res.stderr ?? "") };
}

function readGeneratedCustom(projectConfigDir: string, lang: string): Record<string, unknown> {
  const file = path.join(projectConfigDir, "locales", lang, "custom.json");
  return JSON.parse(fs.readFileSync(file, "utf-8")) as Record<string, unknown>;
}

afterAll(() => {
  for (const dir of tmpDirs) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("build-config.js 导出函数（隔离 PROJECT_CONFIG_DIR）", () => {
  let projectConfigDir: string;
  let mod: BuildConfigModule;

  beforeAll(async () => {
    projectConfigDir = makeTmpDir();
    process.env.PROJECT_CONFIG_DIR = projectConfigDir;
    delete process.env.FILE_UPLOAD_SIZE_LIMIT;
    mod = (await import(/* @vite-ignore */ pathToFileURL(BUILD_CONFIG).href)) as unknown as BuildConfigModule;
  });

  afterAll(() => {
    delete process.env.PROJECT_CONFIG_DIR;
    delete process.env.FILE_UPLOAD_SIZE_LIMIT;
  });

  describe("ensureDir", () => {
    it("UT-FE-AUTO-B8AD6F5D0866704A 递归创建缺失的多层嵌套目录", () => {
      const target = path.join(projectConfigDir, "nested", "a", "b");
      mod.ensureDir(target);
      expect(fs.existsSync(target)).toBe(true);
      expect(fs.statSync(target).isDirectory()).toBe(true);
    });

    it("对已存在目录调用不失败", () => {
      const target = path.join(projectConfigDir, "nested", "a", "b");
      mod.ensureDir(target);
      expect(() => mod.ensureDir(target)).not.toThrow();
    });
  });

  describe("readLocaleConfig", () => {
    it("可配置目录缺失 custom.json 时回退内置 public/locales", () => {
      const zhFile = path.join(projectConfigDir, "locales", "zh", "custom.json");
      fs.rmSync(zhFile, { force: true });
      const result = mod.readLocaleConfig("zh");
      const expected = JSON.parse(fs.readFileSync(BUILT_IN_ZH_CUSTOM, "utf-8"));
      expect(result).toEqual(expected);
    });

    it("JSON 解析异常返回 {} 且不抛出、不返回 undefined", () => {
      const zhDir = path.join(projectConfigDir, "locales", "zh");
      fs.mkdirSync(zhDir, { recursive: true });
      fs.writeFileSync(path.join(zhDir, "custom.json"), "{ not valid json", "utf-8");
      const result = mod.readLocaleConfig("zh");
      expect(result).toEqual({});
      expect(result).not.toBeUndefined();
    });
  });

  describe("saveLocaleConfig", () => {
    it("自动创建子目录、返回 custom.json 且写读一致", () => {
      const ret = mod.saveLocaleConfig('{"FILE_UPLOAD_SIZE_LIMIT":10}', "zh");
      expect(ret).toBe("custom.json");
      expect(mod.readLocaleConfig("zh")).toEqual({ FILE_UPLOAD_SIZE_LIMIT: 10 });
    });
  });
});

describe("FILE_UPLOAD_SIZE_LIMIT 注入与 10-100 钳制（子进程执行）", () => {
  const limitCases: Array<[string | undefined, number]> = [
    [undefined, 10],
    ["150", 100],
    ["5", 10],
    ["abc", 10],
  ];

  it.each(limitCases)("FILE_UPLOAD_SIZE_LIMIT=%s 注入 %i", (limit, expected) => {
    const dir = makeTmpDir();
    const res = runBuildConfig(limit, dir);
    expect(res.status).toBe(0);
    expect(res.stderr).toBe("");
    expect(readGeneratedCustom(dir, "zh").FILE_UPLOAD_SIZE_LIMIT).toBe(expected);
    expect(readGeneratedCustom(dir, "en").FILE_UPLOAD_SIZE_LIMIT).toBe(expected);
  });
});

describe("副作用与产物约束", () => {
  it("全程未改动 frontend/public/locales 内任何文件", () => {
    expect(snapshotBuiltInLocales()).toEqual(builtInBefore);
  });
});
