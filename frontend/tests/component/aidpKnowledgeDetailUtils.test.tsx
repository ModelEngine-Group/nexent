// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { describe, expect, it } from "vitest";

import { parseAidpFailureReason } from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";
import { resizeAidpColumnPair } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";

describe("parseAidpFailureReason", () => {
  it("extracts the code and message from AIDP's JSON string", () => {
    expect(
      parseAidpFailureReason(
        '{"error_code": 1520, "msg": "File Parsing Failed"}'
      )
    ).toEqual({
      raw: '{"error_code": 1520, "msg": "File Parsing Failed"}',
      code: 1520,
      message: "File Parsing Failed",
    });
  });

  it("falls back to the raw text for plain reasons", () => {
    expect(parseAidpFailureReason("File Parsing Failed")).toEqual({
      raw: "File Parsing Failed",
    });
  });

  it("ignores blank and malformed values", () => {
    expect(parseAidpFailureReason(undefined)).toBeNull();
    expect(parseAidpFailureReason("   ")).toBeNull();
    expect(parseAidpFailureReason("{not-json")).toEqual({ raw: "{not-json" });
  });
});

describe("resizeAidpColumnPair", () => {
  it("moves the boundary without changing the total width", () => {
    const widths = { name: 200, size: 100 };
    // The next column stops at the default 64px minimum.
    expect(resizeAidpColumnPair(widths, "name", "size", 40)).toEqual({
      name: 236,
      size: 64,
    });
  });

  it("stops at the per-column minimum widths", () => {
    const widths = { name: 200, size: 100 };
    expect(
      resizeAidpColumnPair(widths, "name", "size", 200, {
        name: 120,
        size: 90,
      })
    ).toEqual({ name: 210, size: 90 });
  });
});
