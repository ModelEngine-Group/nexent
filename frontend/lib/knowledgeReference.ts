// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  KnowledgeFileReference,
  KnowledgeObjectReference,
  KnowledgePictureReference,
} from "@/types/knowledgeReference";
import type { JsonObject, SourceAttributes } from "@/types/source";

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

export function isKnowledgeFileReference(
  value: unknown
): value is KnowledgeFileReference {
  return (
    record(value) &&
    Object.keys(value).length === 3 &&
    Number.isSafeInteger(value.knowledge_id) &&
    (value.knowledge_id as number) > 0 &&
    typeof value.file_id === "string" &&
    /^[0-9a-f]{32}$/.test(value.file_id) &&
    Number.isSafeInteger(value.file_version) &&
    (value.file_version as number) >= 0
  );
}

export function isKnowledgeObjectReference(
  value: unknown
): value is KnowledgeObjectReference {
  return (
    record(value) &&
    Object.keys(value).length === 4 &&
    typeof value.space === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value.space) &&
    typeof value.key === "string" &&
    value.key.length > 0 &&
    value.key.length <= 1024 &&
    !/[\\:]/.test(value.key) &&
    !value.key.split("/").some((part) => ["", ".", ".."].includes(part)) &&
    typeof value.version === "string" &&
    value.version.length > 0 &&
    value.version.length <= 128 &&
    typeof value.sha256 === "string" &&
    /^[0-9a-f]{64}$/.test(value.sha256)
  );
}

/** Parse the wire snapshot separately from provider-specific score metadata. */
export function getKnowledgeSourceAttributes(value: unknown): SourceAttributes {
  if (!record(value) || !isKnowledgeFileReference(value.file_ref)) return {};
  if (value.image_ref != null && !isKnowledgeObjectReference(value.image_ref))
    return {};
  if (value.location != null && !record(value.location)) return {};
  try {
    const snapshot = JSON.stringify({
      file_ref: value.file_ref,
      image_ref: value.image_ref,
      location: value.location,
    });
    if (new TextEncoder().encode(snapshot).length > 16384) return {};
  } catch {
    return {};
  }
  return {
    fileRef: value.file_ref,
    ...(value.image_ref
      ? { imageRef: value.image_ref as KnowledgeObjectReference }
      : {}),
    ...(value.location ? { sourceLocation: value.location as JsonObject } : {}),
  };
}

export function knowledgeReferenceKey(
  source: Pick<SourceAttributes, "fileRef" | "imageRef">
): string | undefined {
  const { fileRef: file, imageRef: image } = source;
  if (!file) return undefined;
  return JSON.stringify([
    file.knowledge_id,
    file.file_id,
    file.file_version,
    ...(image ? [image.space, image.key, image.version, image.sha256] : []),
  ]);
}

export function parseKnowledgePictures(
  value: unknown
): KnowledgePictureReference[] {
  if (!record(value) || !Array.isArray(value.images_ref)) return [];
  return value.images_ref.flatMap((item: unknown) => {
    if (!record(item)) return [];
    const source = getKnowledgeSourceAttributes(item);
    if (
      !source.fileRef ||
      !source.imageRef ||
      !Number.isSafeInteger(item.cite_index) ||
      (item.cite_index as number) < 0 ||
      typeof item.tool_sign !== "string" ||
      !/^[a-z]+$/i.test(item.tool_sign)
    )
      return [];
    return [
      {
        fileRef: source.fileRef,
        imageRef: source.imageRef,
        citeIndex: item.cite_index as number,
        toolSign: item.tool_sign,
      },
    ];
  });
}
