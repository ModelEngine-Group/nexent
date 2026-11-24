// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import JSZip from "jszip";
import { load, JSON_SCHEMA } from "js-yaml";
import type { SkillFileContent } from "../types/skill";

/** Parse locally without uploading; keep the original ZIP for lossless submission. */
export async function parseSkillCreationFile(file: File) {
  const decode = (bytes: Uint8Array) => {
    for (const encoding of ["utf-8", "gb18030", "big5"]) {
      try {
        return new TextDecoder(encoding, { fatal: true }).decode(bytes);
      } catch {
        /* Try the next supported encoding. */
      }
    }
    throw new Error("Unreadable skill text");
  };
  let files: SkillFileContent[];
  if (/\.md$/i.test(file.name)) {
    files = [
      {
        path: "SKILL.md",
        content: decode(new Uint8Array(await file.arrayBuffer())),
      },
    ];
  } else if (/\.zip$/i.test(file.name)) {
    const zip = await JSZip.loadAsync(new Uint8Array(await file.arrayBuffer()));
    const entries = Object.values(zip.files).filter(
      (entry) => !entry.dir && !entry.name.startsWith("__MACOSX/")
    );
    const skillEntry = entries.find(
      (entry) => entry.name.split("/").pop()?.toLowerCase() === "skill.md"
    );
    if (!skillEntry) throw new Error("SKILL.md is missing or unreadable");
    const prefix = skillEntry.name.slice(
      0,
      skillEntry.name.lastIndexOf("/") + 1
    );
    files = await Promise.all(
      entries
        .filter((entry) => entry.name.startsWith(prefix))
        .map(async (entry): Promise<SkillFileContent> => {
          const path = entry.name.slice(prefix.length);
          if (
            !/\.(md|txt|json|csv|html?|xml|ya?ml|toml|ini|py|js|jsx|ts|tsx|sh|css|sql)$/i.test(
              path
            )
          )
            return { path, content: "", status: "unsupported" };
          try {
            return {
              path,
              content: decode(await entry.async("uint8array")),
              status: "readable",
            };
          } catch {
            return { path, content: "", status: "read_error" };
          }
        })
    );
  } else {
    throw new Error("Only Markdown and ZIP skill files are supported");
  }
  const primary = files.find(
    (entry) => entry.path.toLowerCase() === "skill.md"
  );
  if (!primary || primary.status === "read_error")
    throw new Error("SKILL.md is missing or unreadable");
  primary.path = "SKILL.md";
  const match = primary.content
    .replace(/^\uFEFF/, "")
    .match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  const metadata = match ? load(match[1], { schema: JSON_SCHEMA }) : {};
  const fields =
    metadata && typeof metadata === "object" && !Array.isArray(metadata)
      ? (metadata as Record<string, unknown>)
      : {};
  if (match)
    primary.content = primary.content
      .replace(/^\uFEFF/, "")
      .slice(match[0].length);
  return {
    name: typeof fields.name === "string" ? fields.name : "",
    description:
      typeof fields.description === "string" ? fields.description : "",
    tags: Array.isArray(fields.tags)
      ? fields.tags.filter((tag): tag is string => typeof tag === "string")
      : [],
    files: files.sort((a, b) =>
      a.path === "SKILL.md"
        ? -1
        : b.path === "SKILL.md"
          ? 1
          : a.path.localeCompare(b.path)
    ),
  };
}

/** Validate relative draft paths before adding them to a future skill archive. */
export function isValidSkillDraftPath(path: string) {
  return (
    Boolean(path.trim()) &&
    path === path.trim() &&
    !/[\\\x00-\x1f]/.test(path) &&
    !path.startsWith("/") &&
    !/^[a-z]:/i.test(path) &&
    path
      .split("/")
      .every((part) => part !== "" && part !== "." && part !== "..")
  );
}
