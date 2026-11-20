// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import { isCommunityMcpInstalled } from "@/lib/mcpRepositoryInstallation";

describe("MCP repository installation identity", () => {
  const listing = { communityId: 41, name: "vis" };

  it("does not confuse the same name with a different explicit source", () => {
    expect(
      isCommunityMcpInstalled(listing, [
        { communityId: 99, name: "vis", permission: "EDIT" },
      ]),
    ).toBe(false);
  });

  it("recognizes a renamed installed copy by its source", () => {
    expect(
      isCommunityMcpInstalled(listing, [
        { communityId: 41, name: "vis-copy", permission: "EDIT" },
      ]),
    ).toBe(true);
  });

  it.each(["READ_ONLY", undefined] as const)(
    "preserves the existing editable-service rule for permission %s",
    (permission) => {
      expect(
        isCommunityMcpInstalled(listing, [
          { communityId: 41, name: "vis", permission },
        ]),
      ).toBe(false);
    },
  );

  it("preserves name matching for a legacy local service without a source", () => {
    expect(
      isCommunityMcpInstalled(listing, [{ name: "vis", permission: "EDIT" }]),
    ).toBe(true);
  });

  it("preserves name matching when the repository card has no source identity", () => {
    expect(
      isCommunityMcpInstalled({ name: "vis" }, [
        { communityId: 41, name: "vis", permission: "EDIT" },
      ]),
    ).toBe(true);
  });

  it("does not match different names when source identity is unavailable", () => {
    expect(
      isCommunityMcpInstalled(listing, [{ name: "other", permission: "EDIT" }]),
    ).toBe(false);
  });

  it("checks all local services after an unrelated same-name service", () => {
    expect(
      isCommunityMcpInstalled(listing, [
        { communityId: 99, name: "vis", permission: "EDIT" },
        { communityId: 41, name: "renamed", permission: "EDIT" },
      ]),
    ).toBe(true);
  });

  it("returns not installed for an empty list", () => {
    expect(isCommunityMcpInstalled(listing, [])).toBe(false);
  });
});
