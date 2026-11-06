// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export const AGENT_NAME_MAX_LENGTH = 100;
export const AGENT_DISPLAY_NAME_MAX_LENGTH = 60;

const PYTHON_KEYWORDS = new Set([
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
]);
const IDENTIFIER = /^[_\p{ID_Start}][_\p{ID_Continue}]*$/u;

export const isValidAgentName = (name: string): boolean =>
  Array.from(name).length <= AGENT_NAME_MAX_LENGTH &&
  name === name.trim() &&
  IDENTIFIER.test(name) &&
  IDENTIFIER.test(name.normalize("NFKC")) &&
  !PYTHON_KEYWORDS.has(name);
