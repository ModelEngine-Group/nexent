// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  KnowledgeContentRequest,
  KnowledgeFileReference,
  KnowledgeLegacyImageReference,
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

export function isKnowledgeLegacyImageReference(
  value: unknown
): value is KnowledgeLegacyImageReference {
  return (
    record(value) &&
    Object.keys(value).length === 6 &&
    Number.isSafeInteger(value.knowledge_id) &&
    (value.knowledge_id as number) > 0 &&
    typeof value.chunk_key === "string" &&
    value.chunk_key.length > 0 &&
    value.chunk_key.length <= 512 &&
    typeof value.index_uuid === "string" &&
    value.index_uuid.length > 0 &&
    value.index_uuid.length <= 128 &&
    Number.isSafeInteger(value.sequence) &&
    (value.sequence as number) >= 0 &&
    Number.isSafeInteger(value.primary_term) &&
    (value.primary_term as number) > 0 &&
    isKnowledgeObjectReference(value.image_ref) &&
    value.image_ref.space === "files" &&
    value.image_ref.key.startsWith("images_in_attachments/")
  );
}

type ImageSource = Pick<
  SourceAttributes,
  "fileRef" | "imageRef" | "legacyImageRef"
>;

export function knowledgeImageRequest(
  source: ImageSource
): KnowledgeContentRequest | undefined {
  if (source.legacyImageRef) return source.legacyImageRef;
  return source.fileRef && source.imageRef
    ? { ...source.fileRef, image_ref: source.imageRef }
    : undefined;
}

/** Parse the wire snapshot separately from provider-specific score metadata. */
export function getKnowledgeSourceAttributes(value: unknown): SourceAttributes {
  if (!record(value)) return {};
  const {
    file_ref: file,
    image_ref: image,
    legacy_image_ref: legacy,
    location,
  } = value;
  if (
    (file != null && !isKnowledgeFileReference(file)) ||
    (legacy != null && !isKnowledgeLegacyImageReference(legacy)) ||
    (image != null &&
      (!file || legacy || !isKnowledgeObjectReference(image))) ||
    (!file && !legacy) ||
    (file && legacy && file.knowledge_id !== legacy.knowledge_id) ||
    (location != null && !record(location))
  )
    return {};
  try {
    const snapshot = JSON.stringify({
      file_ref: file,
      image_ref: image,
      legacy_image_ref: legacy,
      location,
    });
    if (new TextEncoder().encode(snapshot).length > 16384) return {};
  } catch {
    return {};
  }
  return {
    ...(file ? { fileRef: file } : {}),
    ...(image ? { imageRef: image } : {}),
    ...(legacy ? { legacyImageRef: legacy } : {}),
    ...(location ? { sourceLocation: location as JsonObject } : {}),
  };
}

export function knowledgeReferenceKey(source: ImageSource): string | undefined {
  const { fileRef: file, imageRef: image, legacyImageRef: legacy } = source;
  if (legacy) {
    return JSON.stringify([
      "legacy",
      legacy.knowledge_id,
      legacy.index_uuid,
      legacy.chunk_key,
      legacy.sequence,
      legacy.primary_term,
      legacy.image_ref.space,
      legacy.image_ref.key,
      legacy.image_ref.version,
      legacy.image_ref.sha256,
    ]);
  }
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
  return value.images_ref.flatMap(
    (item: unknown): KnowledgePictureReference[] => {
      if (!record(item)) return [];
      if (
        !Number.isSafeInteger(item.cite_index) ||
        (item.cite_index as number) < 0 ||
        typeof item.tool_sign !== "string" ||
        !/^[a-z]+$/i.test(item.tool_sign)
      )
        return [];
      const source = getKnowledgeSourceAttributes(item);
      const citation = {
        citeIndex: item.cite_index as number,
        toolSign: item.tool_sign,
      };
      if (source.legacyImageRef)
        return [{ legacyImageRef: source.legacyImageRef, ...citation }];
      return source.fileRef && source.imageRef
        ? [{ fileRef: source.fileRef, imageRef: source.imageRef, ...citation }]
        : [];
    }
  );
}
