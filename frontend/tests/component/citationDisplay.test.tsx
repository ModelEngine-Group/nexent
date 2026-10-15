// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import { describe, expect, it } from "vitest";
import {
  buildCitationDisplayIndexMap,
  getCitationKey,
  withCitationDisplayIndices,
} from "@/lib/citationDisplay";

describe("message-wide citation numbering", () => {
  it("counts image citations before a later text source without changing identities", () => {
    const sources = [1, 2, 3, 4].map((citeIndex) =>
      Object.freeze({ citeIndex, toolSign: "a", isImage: citeIndex > 2 })
    );
    const indices = buildCitationDisplayIndexMap(
      [
        {
          type: "text",
          text: "Text [[a1]], figures [[a3]][[a4]], guideline [[a2]]",
        },
      ],
      sources
    );
    const numbered = withCitationDisplayIndices(sources, indices);
    expect(numbered.map((source) => source.displayIndex)).toEqual([1, 4, 2, 3]);
    expect(numbered.map(getCitationKey)).toEqual(["a1", "a2", "a3", "a4"]);
    expect(sources[1]).not.toHaveProperty("displayIndex");
  });

  it("keeps equal raw indices from different tools distinct", () => {
    const sources = [
      { citeIndex: 1, toolSign: "a" },
      { citeIndex: 1, toolSign: "b" },
    ];
    const indices = buildCitationDisplayIndexMap(
      [{ type: "text", text: "[[b1]][[a1]][[b1]]" }],
      sources
    );
    expect(
      withCitationDisplayIndices(sources, indices).map(
        (item) => item.displayIndex
      )
    ).toEqual([2, 1]);
  });

  it("shares one number for normalized markers and numeric legacy aliases", () => {
    const sources = [{ citeIndex: 7, toolSign: "A" }];
    const indices = buildCitationDisplayIndexMap(
      [{ type: "text", text: "[[7]][[ A7 ]][[a7]]" }],
      sources
    );
    expect(indices.get("7")).toBe(1);
    expect(indices.get("a7")).toBe(1);
    expect(withCitationDisplayIndices(sources, indices)[0].displayIndex).toBe(
      1
    );
  });

  it("prefers an exact numeric identity over a tool-prefixed legacy fallback", () => {
    const sources = [{ citeIndex: 1, toolSign: "a" }, { citeIndex: 1 }];
    const indices = buildCitationDisplayIndexMap(
      [{ type: "text", text: "[[1]][[a1]]" }],
      sources
    );
    expect(
      withCitationDisplayIndices(sources, indices).map(
        (item) => item.displayIndex
      )
    ).toEqual([2, 1]);
  });

  it("reserves unknown markers and appends uncited sources without number collisions", () => {
    const sources = [
      { citeIndex: 9, toolSign: "a" },
      { citeIndex: 2, toolSign: "b" },
    ];
    const indices = buildCitationDisplayIndexMap(
      [{ type: "text", text: "[[missing8]][[b2]]" }],
      sources
    );
    expect(indices.get("missing8")).toBe(1);
    expect(
      withCitationDisplayIndices(sources, indices).map(
        (item) => item.displayIndex
      )
    ).toEqual([3, 2]);
  });

  it("ignores non-text parts and leaves invalid source identities unnumbered", () => {
    const sources = [{ citeIndex: undefined }, { citeIndex: Number.NaN }];
    const indices = buildCitationDisplayIndexMap(
      [
        { type: "source", text: "[[a1]]" },
        { type: "text", text: undefined },
      ],
      sources
    );
    expect(indices.size).toBe(0);
    expect(
      withCitationDisplayIndices(sources, indices).map(
        (item) => item.displayIndex
      )
    ).toEqual([undefined, undefined]);
  });
});
