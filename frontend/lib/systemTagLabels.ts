// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { TFunction } from "i18next";

import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import type {
  TagDefinition,
  TagResourcePredicate,
  TagValue,
} from "@/types/tagManagement";

const SYSTEM_DEFINITION_I18N_KEYS: Record<string, string> = {
  agent_category: "tagManagement.systemDefinition.agentCategory",
  keywords: "tagManagement.systemDefinition.keywords",
};

export function getTagDefinitionDisplayName(
  definitionKey: string,
  definitionName: string,
  t: TFunction
): string {
  const i18nKey = SYSTEM_DEFINITION_I18N_KEYS[definitionKey];
  if (!i18nKey) return definitionName;
  const translated = t(i18nKey);
  return translated === i18nKey ? definitionName : translated;
}

export function getTagValueDisplayName(
  definitionKey: string,
  displayValue: string,
  t: TFunction
): string {
  if (definitionKey === "agent_category") {
    return getAgentRepositoryTagLabel(displayValue, t);
  }
  return displayValue;
}

/**
 * Searchable text of a definition row: the localized name rendered in the
 * management table plus the raw key stored by the backend.
 */
function getDefinitionSearchTexts(
  definition: TagDefinition,
  t: TFunction
): string[] {
  return [
    getTagDefinitionDisplayName(
      definition.definition_key,
      definition.definition_name,
      t
    ),
    definition.definition_key,
  ];
}

/**
 * Searchable text of a value row: the localized display value plus the
 * normalized value stored by the backend.
 */
function getValueSearchTexts(
  definition: TagDefinition,
  value: TagValue,
  t: TFunction
): string[] {
  return [
    getTagValueDisplayName(definition.definition_key, value.display_value, t),
    value.normalized_value,
  ];
}

function containsKeyword(
  candidates: Array<string | null | undefined>,
  keyword: string
): boolean {
  return candidates.some((candidate) =>
    (candidate ?? "").toLocaleLowerCase().includes(keyword)
  );
}

export function getTagSearchPredicates(
  definitions: TagDefinition[] | null | undefined,
  search: string,
  t: TFunction
): TagResourcePredicate[] {
  const keyword = search.trim().toLocaleLowerCase();
  if (!keyword) return [];

  return (definitions ?? []).flatMap((definition) => {
    const definitionMatches = containsKeyword(
      getDefinitionSearchTexts(definition, t),
      keyword
    );
    const valueIds = (definition.values ?? [])
      .filter(
        (value) =>
          value.status === "active" &&
          (definitionMatches ||
            containsKeyword(getValueSearchTexts(definition, value, t), keyword))
      )
      .map((value) => value.value_id);
    return valueIds.length > 0
      ? [{ definition_id: definition.definition_id, value_ids: valueIds }]
      : [];
  });
}

/**
 * Resolve the definition ids a management-table search should display.
 *
 * The table renders localized names, while the backend only stores the raw key,
 * so a keyword such as "关键" never reaches the database. Matching therefore
 * runs over the same localized name/key and value texts used elsewhere, and
 * additionally covers every value of the definition regardless of its status so
 * that a row visible in the expanded table can be found by its own values.
 *
 * Returns null when the search is empty, which lets callers skip filtering
 * entirely.
 */
export function getMatchingTagDefinitionIds(
  definitions: TagDefinition[] | null | undefined,
  search: string,
  t: TFunction
): Set<number> | null {
  const keyword = search.trim().toLocaleLowerCase();
  if (!keyword) return null;

  const matched = new Set<number>();
  (definitions ?? []).forEach((definition) => {
    if (containsKeyword(getDefinitionSearchTexts(definition, t), keyword)) {
      matched.add(definition.definition_id);
      return;
    }
    const hasMatchingValue = (definition.values ?? []).some((value) =>
      containsKeyword(getValueSearchTexts(definition, value, t), keyword)
    );
    if (hasMatchingValue) matched.add(definition.definition_id);
  });
  return matched;
}
