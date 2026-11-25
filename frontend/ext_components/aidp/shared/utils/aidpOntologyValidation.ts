// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Shared client-side limits for ontology forms. Values mirror the AIDP contract. */

import type { TFunction } from "i18next";

export const ONTOLOGY_NAME_MAX_CHARS = 64;
export const ONTOLOGY_NAME_MAX_BYTES = 64;
export const ONTOLOGY_DESCRIPTION_MAX_CHARS = 512;
export const ONTOLOGY_DESCRIPTION_MAX_BYTES = 512;
export const METADATA_FIELD_NAME_MAX_CHARS = 63;
export const METADATA_FIELD_NAME_MAX_BYTES = 64;
export const METADATA_FIELD_LIMIT = 20;
export const ENTITY_API_NAME_MAX_CHARS = 64;
export const ENTITY_NAME_MAX_BYTES = 64;
export const ENTITY_DESCRIPTION_MAX_CHARS = 512;
export const ENTITY_DESCRIPTION_MAX_BYTES = 512;
export const RULE_NAME_MAX_BYTES = 128;
export const RULE_DESCRIPTION_MAX_BYTES = 512;

export const utf8ByteLength = (value: string): number =>
  new TextEncoder().encode(value).length;

/** Counter text for byte-limited inputs, e.g. `18/64 字节`. */
export const byteCountText = (
  value: string,
  maxBytes: number,
  unit: string
): string => `${utf8ByteLength(value)}/${maxBytes} ${unit}`;

export const validateOntologyName = (
  value: string,
  t: TFunction
): string | null => {
  const name = value.trim();
  if (!name) return t("aidpKnowledge.ontologyNameRequired");
  if (name.length > ONTOLOGY_NAME_MAX_CHARS) {
    return t("aidpKnowledge.ontologyNameTooLongChars", {
      max: ONTOLOGY_NAME_MAX_CHARS,
      current: name.length,
    });
  }
  const bytes = utf8ByteLength(name);
  if (bytes > ONTOLOGY_NAME_MAX_BYTES) {
    return t("aidpKnowledge.ontologyNameTooLongBytes", {
      max: ONTOLOGY_NAME_MAX_BYTES,
      current: bytes,
    });
  }
  return null;
};

export const validateOntologyDescription = (
  value: string,
  t: TFunction
): string | null => {
  const description = value.trim();
  if (description.length > ONTOLOGY_DESCRIPTION_MAX_CHARS) {
    return t("aidpKnowledge.ontologyDescriptionTooLongChars", {
      max: ONTOLOGY_DESCRIPTION_MAX_CHARS,
      current: description.length,
    });
  }
  const bytes = utf8ByteLength(description);
  if (bytes > ONTOLOGY_DESCRIPTION_MAX_BYTES) {
    return t("aidpKnowledge.ontologyDescriptionTooLongBytes", {
      max: ONTOLOGY_DESCRIPTION_MAX_BYTES,
      current: bytes,
    });
  }
  return null;
};

export const validateEntityName = (
  value: string,
  t: TFunction
): string | null => {
  const name = value.trim();
  if (!name) return t("aidpKnowledge.ontologyEntityNameRequired");
  const bytes = utf8ByteLength(name);
  if (bytes > ENTITY_NAME_MAX_BYTES) {
    return t("aidpKnowledge.ontologyEntityNameTooLongBytes", {
      max: ENTITY_NAME_MAX_BYTES,
      current: bytes,
    });
  }
  return null;
};

export const validateEntityDescription = (
  value: string,
  t: TFunction
): string | null => {
  const description = value.trim();
  const bytes = utf8ByteLength(description);
  if (bytes > ENTITY_DESCRIPTION_MAX_BYTES) {
    return t("aidpKnowledge.ontologyEntityDescriptionTooLongBytes", {
      max: ENTITY_DESCRIPTION_MAX_BYTES,
      current: bytes,
    });
  }
  return null;
};

export const validateRuleName = (
  value: string,
  t: TFunction
): string | null => {
  const name = value.trim();
  if (!name) return t("aidpKnowledge.ontologyRuleNameRequired");
  const bytes = utf8ByteLength(name);
  if (bytes > RULE_NAME_MAX_BYTES) {
    return t("aidpKnowledge.ontologyRuleNameTooLongBytes", {
      max: RULE_NAME_MAX_BYTES,
      current: bytes,
    });
  }
  return null;
};

export const validateRuleDescription = (
  value: string,
  t: TFunction
): string | null => {
  const description = value.trim();
  const bytes = utf8ByteLength(description);
  if (bytes > RULE_DESCRIPTION_MAX_BYTES) {
    return t("aidpKnowledge.ontologyRuleDescriptionTooLongBytes", {
      max: RULE_DESCRIPTION_MAX_BYTES,
      current: bytes,
    });
  }
  return null;
};

export const validateFieldName = (
  value: string,
  t: TFunction
): string | null => {
  const name = value.trim();
  if (!name) return t("aidpKnowledge.ontologyFieldNameRequired");
  if (name.length > METADATA_FIELD_NAME_MAX_CHARS) {
    return t("aidpKnowledge.ontologyFieldNameTooLongChars", {
      max: METADATA_FIELD_NAME_MAX_CHARS,
    });
  }
  if (utf8ByteLength(name) > METADATA_FIELD_NAME_MAX_BYTES) {
    return t("aidpKnowledge.ontologyFieldNameTooLongBytes", {
      max: METADATA_FIELD_NAME_MAX_BYTES,
    });
  }
  return null;
};
