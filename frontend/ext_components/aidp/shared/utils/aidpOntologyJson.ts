// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { TFunction } from "i18next";

import type {
  AidpOntologyImportPreview,
  AidpOntologyJsonDocument,
} from "../types/ontology";

interface PreviewError {
  field: string;
  message: string;
}

const MAX_PREVIEW_ERRORS = 50;

function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function locateGroups(
  document: AidpOntologyJsonDocument
): Record<string, unknown>[] {
  if (["types", "entities", "relations"].some((key) => key in document)) {
    return [document];
  }
  return Object.values(document).filter(
    (value): value is Record<string, unknown> =>
      !!value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      ["types", "entities", "relations"].some((key) => key in (value as object))
  );
}

/**
 * Validate an exported ontology file and count its objects for the import
 * drawer. The authoritative conversion still happens in the backend; this
 * preview only lets the browser report structural problems before uploading.
 */
export function previewOntologyImport(
  document: AidpOntologyJsonDocument,
  fileName: string,
  targetDomainName: string,
  t: TFunction
): AidpOntologyImportPreview {
  const errors: PreviewError[] = [];
  const preview: AidpOntologyImportPreview = {
    fileName,
    domainKey: null,
    targetDomainName,
    typeCount: 0,
    entityCount: 0,
    relationCount: 0,
    errors,
  };

  if (!document || typeof document !== "object" || Array.isArray(document)) {
    errors.push({
      field: "$",
      message: t("aidpKnowledge.ontologyImportJsonTopLevelObject"),
    });
    return preview;
  }

  const groupKeys = Object.keys(document);
  if (!["types", "entities", "relations"].some((key) => key in document)) {
    const firstGroup = groupKeys.find((key) => {
      const value = document[key];
      return (
        !!value &&
        typeof value === "object" &&
        !Array.isArray(value) &&
        ["types", "entities", "relations"].some(
          (field) => field in (value as object)
        )
      );
    });
    if (!firstGroup) {
      errors.push({
        field: "$",
        message: t("aidpKnowledge.ontologyImportJsonGroupMissing"),
      });
      return preview;
    }
    preview.domainKey = firstGroup;
  }

  const groups = locateGroups(document);
  const entityKinds = new Map<string, Set<string>>();
  const seen = new Set<string>();

  for (const group of groups) {
    for (const [kind, field] of [
      ["type", "types"],
      ["entity", "entities"],
    ] as const) {
      const raw = group[field];
      if (raw === undefined) continue;
      if (!Array.isArray(raw)) {
        errors.push({
          field,
          message: t("aidpKnowledge.ontologyImportFieldMustBeArray", {
            field,
          }),
        });
        continue;
      }
      raw.forEach((item, index) => {
        if (!item || typeof item !== "object" || Array.isArray(item)) {
          errors.push({
            field: `${field}[${index}]`,
            message: t("aidpKnowledge.ontologyImportItemMustBeObject"),
          });
          return;
        }
        const apiName = asText((item as Record<string, unknown>).api_name);
        if (!apiName) {
          errors.push({
            field: `${field}[${index}].api_name`,
            message: t("aidpKnowledge.ontologyImportApiNameRequired"),
          });
          return;
        }
        if (seen.has(`${apiName}:${kind}`)) {
          errors.push({
            field: `${field}[${index}].api_name`,
            message: t("aidpKnowledge.ontologyImportDuplicateApiName"),
          });
          return;
        }
        seen.add(`${apiName}:${kind}`);
        const kinds = entityKinds.get(apiName) ?? new Set<string>();
        kinds.add(kind);
        entityKinds.set(apiName, kinds);
        if (kind === "type") preview.typeCount += 1;
        else preview.entityCount += 1;
      });
    }
  }

  for (const group of groups) {
    const raw = group.relations;
    if (raw === undefined) continue;
    if (!Array.isArray(raw)) {
      errors.push({
        field: "relations",
        message: t("aidpKnowledge.ontologyImportFieldMustBeArray", {
          field: "relations",
        }),
      });
      continue;
    }
    raw.forEach((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        errors.push({
          field: `relations[${index}]`,
          message: t("aidpKnowledge.ontologyImportItemMustBeObject"),
        });
        return;
      }
      const relation = item as Record<string, unknown>;
      const apiName = asText(relation.api_name);
      if (!apiName) {
        errors.push({
          field: `relations[${index}].api_name`,
          message: t("aidpKnowledge.ontologyImportApiNameRequired"),
        });
        return;
      }
      for (const [endpointField, kindField] of [
        ["source_api_name", "source_kind"],
        ["object_api_name", "object_kind"],
      ] as const) {
        const endpoint = asText(relation[endpointField]);
        if (!endpoint) {
          errors.push({
            field: `relations[${index}].${endpointField}`,
            message: t("aidpKnowledge.ontologyImportRelationEndpointRequired", {
              field: endpointField,
            }),
          });
          continue;
        }
        const kinds = entityKinds.get(endpoint);
        if (!kinds) {
          errors.push({
            field: `relations[${index}].${endpointField}`,
            message: t("aidpKnowledge.ontologyImportRelationEndpointMissing", {
              endpoint,
            }),
          });
          continue;
        }
        const declared = asText(relation[kindField]).toLowerCase();
        if (declared && !kinds.has(declared)) {
          errors.push({
            field: `relations[${index}].${kindField}`,
            message: t("aidpKnowledge.ontologyImportRelationKindMismatch", {
              endpoint,
              declared,
            }),
          });
        } else if (!declared && kinds.size > 1) {
          errors.push({
            field: `relations[${index}].${kindField}`,
            message: t("aidpKnowledge.ontologyImportRelationKindAmbiguous", {
              endpoint,
              field: kindField,
            }),
          });
        }
      }
      preview.relationCount += 1;
    });
  }

  if (errors.length > MAX_PREVIEW_ERRORS) {
    preview.errors = errors.slice(0, MAX_PREVIEW_ERRORS);
  }
  return preview;
}

/** Parse a selected file and return either the document or a readable error. */
export function parseOntologyJson(
  text: string,
  t: TFunction
): {
  document?: AidpOntologyJsonDocument;
  error?: string;
} {
  try {
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: t("aidpKnowledge.ontologyImportJsonTopLevelObject") };
    }
    return { document: parsed as AidpOntologyJsonDocument };
  } catch {
    return { error: t("aidpKnowledge.ontologyImportInvalidJson") };
  }
}
