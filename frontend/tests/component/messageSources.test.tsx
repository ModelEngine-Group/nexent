// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import {
  getMessageSources,
  findMessageSource,
} from "@/app/newchat/ui/message-sources";

describe("message-wide source snapshots", () => {
  it("shares stable numbered items and preserves exact and numeric citation lookup", () => {
    const content = [
      { type: "text", text: "Last hit first [[j300]], then [[a1]]" },
      {
        type: "source",
        citeIndex: 1,
        toolSign: "a",
        sourceType: "file",
        title: "First",
      },
      {
        type: "source",
        citeIndex: 300,
        toolSign: "j",
        title: "Last",
        sourceMetadata: { key: "value" },
      },
    ];
    const model = getMessageSources("message", content);
    expect(getMessageSources("message", content)).toBe(model);
    expect(findMessageSource(model, " J300 ")).toBe(model.sources[1]);
    expect(model.sources[1].displayIndex).toBe(1);
    expect(findMessageSource(model, "1")).toBe(model.sources[0]);
    expect(findMessageSource(model, "b1")).toBeUndefined();
    expect(model.sources[0].sourceType).toBe("document");
    expect(model.sources[1].sourceMetadata).toBe(content[2].sourceMetadata);
  });

  it("invalidates changed content and late registry data without crossing message IDs", () => {
    const content = [{ type: "text", text: "Streaming [[j1]]" }];
    const before = getMessageSources("stream", content);
    expect(before.sources).toHaveLength(0);
    const registry = [
      {
        citeIndex: 1,
        toolSign: "j",
        title: "Retrieved",
        url: "",
        sourceType: "file",
      },
    ];
    const after = getMessageSources("stream", content, registry);
    expect(after).not.toBe(before);
    expect(after.sources[0].title).toBe("Retrieved");
    expect(getMessageSources("other", content, registry)).not.toBe(after);
    const changed = getMessageSources(
      "stream",
      [
        ...content,
        { type: "source", citeIndex: 2, toolSign: "a", title: "Persisted" },
      ],
      registry
    );
    expect(changed.sources[0].title).toBe("Persisted");
    expect(findMessageSource(changed, "j1")?.title).toBe("Retrieved");
  });

  it("keeps registry-only images and uses content for overlapping source identities", () => {
    const content = [
      { type: "source", citeIndex: 1, toolSign: "a", title: "Persisted title" },
    ];
    const registry = [
      { citeIndex: 1, toolSign: "a", title: "Old title", url: "" },
      {
        citeIndex: 2,
        toolSign: "b",
        title: "Image",
        url: "image.png",
        isImage: true,
      },
    ];
    const model = getMessageSources("mixed", content, registry);
    expect(model.all).toHaveLength(2);
    expect(model.sources[0].title).toBe("Persisted title");
    expect(model.images).toHaveLength(1);
    expect(findMessageSource(model, "b2")).toBe(model.images[0]);
  });
});
