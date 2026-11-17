// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import {
  getKnowledgeSourceAttributes,
  knowledgeReferenceKey,
  parseKnowledgePictures,
} from "@/lib/knowledgeReference";

const file_ref = { knowledge_id: 7, file_id: "a".repeat(32), file_version: 0 };
const image_ref = {
  space: "files",
  key: "kb/image.png",
  version: "v1",
  sha256: "b".repeat(64),
};

describe("versioned knowledge references", () => {
  it("preserves fixed identity and location without guessing a URL", () => {
    expect(
      getKnowledgeSourceAttributes({
        file_ref,
        image_ref,
        location: { page: 2 },
      })
    ).toEqual({
      fileRef: file_ref,
      imageRef: image_ref,
      sourceLocation: { page: 2 },
    });
    expect(
      getKnowledgeSourceAttributes({
        url: "s3://files/kb/image.png",
        filename: "image.png",
      })
    ).toEqual({});
  });

  it.each([
    { file_ref: { ...file_ref, knowledge_id: 0 } },
    { file_ref: { ...file_ref, file_version: -1 } },
    { file_ref: { ...file_ref, file_version: 1.5 } },
    { file_ref: { ...file_ref, file_id: "unknown" } },
    { image_ref },
    { file_ref, location: [] },
    { file_ref, location: { text: "界".repeat(6000) } },
    { file_ref, image_ref: { ...image_ref, key: "https://example.com/x" } },
    { file_ref, image_ref: { ...image_ref, key: "kb/../x" } },
    { file_ref, image_ref: { ...image_ref, sha256: "bad" } },
  ])("rejects malformed identity as a whole", (value) => {
    expect(getKnowledgeSourceAttributes(value)).toEqual({});
  });

  it("only restores selected, valid picture references with their citation", () => {
    const good = { file_ref, image_ref, cite_index: 3, tool_sign: "a" };
    const pictures = parseKnowledgePictures({
      images_ref: [
        good,
        { ...good, image_ref: undefined },
        { ...good, cite_index: -1 },
      ],
    });
    expect(pictures).toEqual([
      { fileRef: file_ref, imageRef: image_ref, citeIndex: 3, toolSign: "a" },
    ]);
    expect(knowledgeReferenceKey(pictures[0])).not.toBe(
      knowledgeReferenceKey({
        ...pictures[0],
        fileRef: { ...file_ref, file_version: 1 },
      })
    );
    expect(knowledgeReferenceKey(pictures[0])).not.toBe(
      knowledgeReferenceKey({
        ...pictures[0],
        imageRef: { ...image_ref, version: "v2" },
      })
    );
  });
});
