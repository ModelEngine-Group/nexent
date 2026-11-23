// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Human-readable labels for the rule operators supported by AIDP. */
export const RULE_OPERATOR_LABELS: Record<string, string> = {
  is: "等于",
  "is not": "不等于",
  "start with": "开头是",
  "end with": "结尾是",
  in: "包含",
  not_in: "不包含",
  exists: "存在",
  not_exists: "不存在",
  before: "早于",
  after: "晚于",
  "=": "等于",
  "!=": "不等于",
  ">": "大于",
  "<": "小于",
  ">=": "大于等于",
  "<=": "小于等于",
  // Legacy values may still be present in old rules.
  is_not: "不等于",
  contains: "包含",
  not_contains: "不包含",
  starts_with: "开头是",
  ends_with: "结尾是",
  gt: "大于",
  gte: "大于等于",
  lt: "小于",
  lte: "小于等于",
  empty: "为空",
  not_empty: "不为空",
  "not empty": "不为空",
};

export const ruleOperatorLabel = (operator: string): string =>
  RULE_OPERATOR_LABELS[operator] ?? operator;
