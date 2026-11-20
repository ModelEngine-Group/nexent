// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it, vi } from "vitest";

vi.mock("@/base-path.mjs", () => ({ BASE_PATH: "/nexent" }));

import { RESOURCE_REPOSITORY_PERMISSION_ROUTE } from "@/const/resourceRepository";
import {
  buildResourceRepositoryHref,
  normalizeRepositoryId,
  parseResourceRepositoryTarget,
} from "@/lib/resourceRepositoryRoutes";

describe("resource repository navigation", () => {
  it("keeps BIGINT identity, locale and basePath in external review links", () => {
    const href = buildResourceRepositoryHref("zh", {
      tab: "review",
      resourceType: "mcp",
      repositoryId: "9223372036854775807",
    });
    expect(href).toBe(
      "/nexent/zh/resource-space?tab=review&resource_type=mcp&repository_id=9223372036854775807"
    );
    expect(RESOURCE_REPOSITORY_PERMISSION_ROUTE).toBe("/resource-space");
    expect(
      parseResourceRepositoryTarget(
        new URL(href, "http://localhost").searchParams
      )
    ).toEqual({
      valid: true,
      target: {
        tab: "review",
        resourceType: "mcp",
        repositoryId: "9223372036854775807",
      },
    });
  });

  it("removes the agent mine target and retains mine targets for MCP and Skill", () => {
    expect(
      parseResourceRepositoryTarget(new URLSearchParams("tab=agent&view=mine"))
    ).toMatchObject({ valid: false });
    for (const tab of ["mcp", "skill"] as const) {
      expect(
        parseResourceRepositoryTarget(
          new URLSearchParams({ tab, view: "mine" })
        )
      ).toEqual({
        valid: true,
        target: { tab, view: "mine" },
      });
    }
  });

  it.each(["agent", "mcp", "skill", "review"] as const)(
    "restores the explicit %s tab",
    (tab) => {
      expect(
        parseResourceRepositoryTarget(new URLSearchParams({ tab }))
      ).toEqual({ valid: true, target: { tab } });
    }
  );

  it("defaults only when no explicit tab was supplied", () => {
    expect(parseResourceRepositoryTarget(new URLSearchParams())).toEqual({
      valid: true,
      target: { tab: "agent" },
    });
    expect(
      parseResourceRepositoryTarget(new URLSearchParams("tab="))
    ).toMatchObject({ valid: false });
  });

  it.each([
    "tab=other",
    "tab=skill&resource_type=mcp",
    "tab=review&repository_id=10",
    "tab=mcp&skill_id=10",
    "tab=skill&agent_id=10",
    "tab=review&tab=agent",
    "tab=agent&view=repository&onboarding=1",
    "tab=skill&repository_id=1e3",
  ])("rejects invalid or conflicting targets: %s", (query) => {
    expect(
      parseResourceRepositoryTarget(new URLSearchParams(query))
    ).toMatchObject({ valid: false });
  });

  it.each([
    0,
    -1,
    1.1,
    Number.MAX_SAFE_INTEGER + 1,
    "01",
    "9223372036854775808",
    "1e3",
    null,
  ])("rejects an unsafe identity %s", (value) =>
    expect(normalizeRepositoryId(value)).toBeNull()
  );

  it("accepts safe legacy numbers and exact string IDs", () => {
    expect(normalizeRepositoryId(123)).toBe("123");
    expect(normalizeRepositoryId("9007199254740993")).toBe("9007199254740993");
  });

  it("does not build a path from an invalid locale or conflicting target", () => {
    expect(() =>
      buildResourceRepositoryHref("../zh", { tab: "agent" })
    ).toThrow();
    expect(() =>
      buildResourceRepositoryHref("zh", { tab: "mcp", skillId: "1" })
    ).toThrow();
  });
});
