// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { TFunction } from "i18next";

/** Locale keys for the rule operators supported by AIDP. */
export const RULE_OPERATOR_LABEL_KEYS: Record<string, string> = {
  is: "aidpKnowledge.ontologyRuleOperatorEquals",
  "is not": "aidpKnowledge.ontologyRuleOperatorNotEquals",
  "start with": "aidpKnowledge.ontologyRuleOperatorStartsWith",
  "end with": "aidpKnowledge.ontologyRuleOperatorEndsWith",
  in: "aidpKnowledge.ontologyRuleOperatorContains",
  not_in: "aidpKnowledge.ontologyRuleOperatorNotContains",
  exists: "aidpKnowledge.ontologyRuleOperatorExists",
  not_exists: "aidpKnowledge.ontologyRuleOperatorNotExists",
  before: "aidpKnowledge.ontologyRuleOperatorBefore",
  after: "aidpKnowledge.ontologyRuleOperatorAfter",
  "=": "aidpKnowledge.ontologyRuleOperatorEquals",
  "!=": "aidpKnowledge.ontologyRuleOperatorNotEquals",
  ">": "aidpKnowledge.ontologyRuleOperatorGreaterThan",
  "<": "aidpKnowledge.ontologyRuleOperatorLessThan",
  ">=": "aidpKnowledge.ontologyRuleOperatorGreaterThanOrEqual",
  "<=": "aidpKnowledge.ontologyRuleOperatorLessThanOrEqual",
  // Legacy values may still be present in old rules.
  is_not: "aidpKnowledge.ontologyRuleOperatorNotEquals",
  contains: "aidpKnowledge.ontologyRuleOperatorContains",
  not_contains: "aidpKnowledge.ontologyRuleOperatorNotContains",
  starts_with: "aidpKnowledge.ontologyRuleOperatorStartsWith",
  ends_with: "aidpKnowledge.ontologyRuleOperatorEndsWith",
  gt: "aidpKnowledge.ontologyRuleOperatorGreaterThan",
  gte: "aidpKnowledge.ontologyRuleOperatorGreaterThanOrEqual",
  lt: "aidpKnowledge.ontologyRuleOperatorLessThan",
  lte: "aidpKnowledge.ontologyRuleOperatorLessThanOrEqual",
  empty: "aidpKnowledge.ontologyRuleOperatorEmpty",
  not_empty: "aidpKnowledge.ontologyRuleOperatorNotEmpty",
  "not empty": "aidpKnowledge.ontologyRuleOperatorNotEmpty",
};

export const ruleOperatorLabel = (operator: string, t: TFunction): string => {
  const key = RULE_OPERATOR_LABEL_KEYS[operator];
  return key ? t(key) : operator;
};
