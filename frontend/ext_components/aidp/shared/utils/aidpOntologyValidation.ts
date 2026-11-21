// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Shared client-side limits for ontology forms. Values mirror the AIDP contract. */

export const ONTOLOGY_NAME_MAX_CHARS = 64;
export const ONTOLOGY_DESCRIPTION_MAX_CHARS = 512;
export const METADATA_FIELD_NAME_MAX_CHARS = 63;
export const METADATA_FIELD_NAME_MAX_BYTES = 64;
export const METADATA_FIELD_LIMIT = 20;
export const ENTITY_API_NAME_MAX_CHARS = 64;
export const ENTITY_DESCRIPTION_MAX_CHARS = 512;

export const utf8ByteLength = (value: string): number =>
  new TextEncoder().encode(value).length;

export const validateOntologyName = (value: string): string | null => {
  const name = value.trim();
  if (!name) return "请输入本体库名称";
  if (name.length > ONTOLOGY_NAME_MAX_CHARS) {
    return `名称不能超过 ${ONTOLOGY_NAME_MAX_CHARS} 个字符（当前 ${name.length} 个字符）`;
  }
  return null;
};

export const validateOntologyDescription = (value: string): string | null => {
  const description = value.trim();
  if (description.length > ONTOLOGY_DESCRIPTION_MAX_CHARS) {
    return `描述不能超过 ${ONTOLOGY_DESCRIPTION_MAX_CHARS} 个字符（当前 ${description.length} 个字符）`;
  }
  return null;
};

export const validateFieldName = (value: string): string | null => {
  const name = value.trim();
  if (!name) return "请输入字段名";
  if (name.length > METADATA_FIELD_NAME_MAX_CHARS) {
    return `字段名不能超过 ${METADATA_FIELD_NAME_MAX_CHARS} 个字符`;
  }
  if (utf8ByteLength(name) > METADATA_FIELD_NAME_MAX_BYTES) {
    return `字段名不能超过 ${METADATA_FIELD_NAME_MAX_BYTES} 字节`;
  }
  return null;
};
