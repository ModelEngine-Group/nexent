import type { AidpKbColumnKey } from "./types";

/** Columns the user cannot hide: the entry point and the row actions. */
export const AIDP_KB_REQUIRED_COLUMNS: AidpKbColumnKey[] = ["name", "actions"];

/** Default visible column set, used on first render and by "restore". */
export const AIDP_KB_DEFAULT_COLUMNS: AidpKbColumnKey[] = [
  "name",
  "type",
  "description",
  "creator",
  "created_at",
  "actions",
];

export const COLUMN_LABEL_KEYS: Record<AidpKbColumnKey, string> = {
  name: "aidpKnowledge.columnName",
  type: "aidpKnowledge.columnType",
  description: "aidpKnowledge.columnDescription",
  creator: "aidpKnowledge.columnCreator",
  created_at: "aidpKnowledge.columnCreatedAt",
  actions: "aidpKnowledge.columnActions",
};

export const BASE_COLUMN_WEIGHTS: Record<AidpKbColumnKey, number> = {
  name: 280,
  type: 260,
  description: 418,
  creator: 180,
  created_at: 160,
  actions: 144,
};

// Debounce for the AIDP knowledge-base search box. Keystrokes are coalesced
// until the user pauses for this long, so typing "report" issues one request
// instead of six.
export const KB_SEARCH_DEBOUNCE_MS = 300;
