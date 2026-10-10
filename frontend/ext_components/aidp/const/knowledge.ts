// Keep this pattern in sync with AIDP's knowledge-base name validation.
export const AIDP_KNOWLEDGE_BASE_NAME_PATTERN =
  /^[\u4e00-\u9fa5a-zA-Z][\u4e00-\u9fa5a-zA-Z0-9_]{0,255}$/;

// Debounce for the AIDP knowledge-base search box. Keystrokes are coalesced
// until the user pauses for this long, so typing "report" issues one request
// instead of six.
export const KB_SEARCH_DEBOUNCE_MS = 300;
