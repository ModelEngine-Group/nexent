import { describe, expect, it } from "vitest";

import { normalizeTags } from "@/services/agentConfigService";

describe("normalizeTags", () => {
  it("passes arrays through while trimming and dropping empty entries", () => {
    expect(normalizeTags(["a", "", "  b  "])).toEqual(["a", "b"]);
    expect(normalizeTags([])).toEqual([]);
  });

  it("recovers tags from a JSON-encoded stringified array", () => {
    expect(normalizeTags('["a","b"]')).toEqual(["a", "b"]);
    expect(normalizeTags('["a", "", "b"]')).toEqual(["a", "b"]);
  });

  it("recovers tags from a Python-repr stringified array", () => {
    expect(normalizeTags("['a', 'b']")).toEqual(["a", "b"]);
    expect(normalizeTags("['a', None, True]")).toEqual(["a"]);
  });

  it("treats a plain non-empty scalar as a single tag", () => {
    expect(normalizeTags("medical")).toEqual(["medical"]);
    expect(normalizeTags("  medical  ")).toEqual(["medical"]);
    expect(normalizeTags("")).toEqual([]);
    expect(normalizeTags("   ")).toEqual([]);
  });

  it("ignores unrecoverable array-like values instead of crashing", () => {
    expect(normalizeTags("[garbage]")).toEqual([]);
  });

  it("returns an empty array for non-string, non-array values", () => {
    expect(normalizeTags(null)).toEqual([]);
    expect(normalizeTags(undefined)).toEqual([]);
    expect(normalizeTags(42)).toEqual([]);
    expect(normalizeTags({ tag: "a" })).toEqual([]);
  });
});
