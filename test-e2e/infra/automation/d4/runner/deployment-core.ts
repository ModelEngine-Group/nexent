// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { Page } from "playwright/test";

import { FixtureUnavailableError, readFixtureConfig } from "./journey";

type AgentCore = "smolagents" | "jiuwen";

const execute = promisify(execFile);

export function deploymentCoreSwitch(page: Page, baseUrl: string) {
  const config = readFixtureConfig("NEXENT_E2E_CORE_SWITCH_CONFIG");
  const base = new URL(baseUrl);
  const argv = config.argv;
  if (
    !["127.0.0.1", "localhost"].includes(base.hostname) ||
    new URL(config.base_url).origin !== base.origin ||
    !Array.isArray(argv) || !argv.length ||
    !argv.every((part: unknown) => typeof part === "string" && part.length) ||
    typeof config.fixture_container !== "string" ||
    config.fixture_container === "nexent-config" ||
    !/^\/[\w.-]+(?:\/[\w.-]+)*$/.test(config.fixture_directory) ||
    config.fixture_directory.split("/").some((part: string) => part === "..")
  ) {
    throw new FixtureUnavailableError("Configure a core switch driver for the isolated test deployment.");
  }

  const deployedCore = async (): Promise<AgentCore> => {
    const response = await page.request.get(new URL("/api/tenant_config/deployment_version", base).href);
    if (!response.ok()) throw new Error("Cannot verify the test deployment Core through Gateway.");
    const core = (await response.json()).agent_core;
    if (core !== "jiuwen" && core !== "smolagents") throw new Error("Unexpected deployment Core.");
    return core;
  };

  let original: AgentCore | undefined;
  const select = async (core: AgentCore) => {
    const current = await deployedCore();
    original ??= current;
    if (current === core) return;
    try {
      await execute(argv[0], [...argv.slice(1), core], { timeout: 180000 });
    } catch {
      throw new Error("The isolated Core switch driver failed. Check the machine-local deployment log.");
    }
    if ((await deployedCore()) !== core) throw new Error("Deployment Core did not match the requested mode.");
  };

  return {
    fixtureContainer: config.fixture_container as string,
    fixtureDirectory: config.fixture_directory as string,
    select,
    restore: async () => {
      if (original) await select(original);
    },
  };
}
