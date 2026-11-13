// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { File as NativeFile } from "node:buffer";
import JSZip from "jszip";
import { expect, test } from "vitest";
import {
  isValidSkillDraftPath,
  parseSkillCreationFile,
} from "@/lib/skillCreationDraft";

const asFile = (file: NativeFile) => file as unknown as File;

test("parses Markdown metadata and keeps one editable body without duplicate frontmatter", async () => {
  const result = await parseSkillCreationFile(
    asFile(
      new NativeFile(
        [
          "---\nname: example\ndescription: Description\ntags: [finance]\n---\n# Body",
        ],
        "example.md"
      )
    )
  );
  expect(result).toMatchObject({
    name: "example",
    description: "Description",
    tags: ["finance"],
  });
  expect(result.files).toEqual([{ path: "SKILL.md", content: "# Body" }]);
});

test("parses nested ZIP files and marks binary assets without decoding them", async () => {
  const zip = new JSZip();
  zip.file(
    "example/SKILL.md",
    "---\nname: zip-skill\ndescription: ZIP skill\n---\nBody"
  );
  zip.file("example/scripts/helper.py", "print('hello')");
  zip.file("example/assets/picture.png", new Uint8Array([0, 255, 1]));
  const result = await parseSkillCreationFile(
    asFile(
      new NativeFile(
        [await zip.generateAsync({ type: "uint8array" })],
        "example.zip"
      )
    )
  );
  expect(result.files[0]).toMatchObject({ path: "SKILL.md", content: "Body" });
  expect(result.files).toContainEqual({
    path: "assets/picture.png",
    content: "",
    status: "unsupported",
  });
  expect(result.files).toContainEqual({
    path: "scripts/helper.py",
    content: "print('hello')",
    status: "readable",
  });
});

test("rejects unsupported input, corrupt ZIPs and missing primary files", async () => {
  await expect(
    parseSkillCreationFile(asFile(new NativeFile(["text"], "file.txt")))
  ).rejects.toThrow();
  await expect(
    parseSkillCreationFile(asFile(new NativeFile(["bad archive"], "file.zip")))
  ).rejects.toThrow();
  const zip = new JSZip();
  zip.file("README.md", "Missing primary");
  await expect(
    parseSkillCreationFile(
      asFile(
        new NativeFile(
          [await zip.generateAsync({ type: "uint8array" })],
          "file.zip"
        )
      )
    )
  ).rejects.toThrow("SKILL.md");
});

test.each([
  "",
  "/absolute.txt",
  "../escape.py",
  "a/../escape.py",
  "a//file.py",
  "C:/file.py",
  "a\\file.py",
  " file.py",
])("rejects invalid draft path %s", (path) => {
  expect(isValidSkillDraftPath(path)).toBe(false);
});

test("accepts nested relative file paths", () => {
  expect(isValidSkillDraftPath("scripts/nested/helper.py")).toBe(true);
});
