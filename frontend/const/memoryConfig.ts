// Memory share strategy constants
export const MEMORY_SHARE_STRATEGY = {
  ALWAYS: "always",
  ASK: "ask", 
  NEVER: "never",
} as const;

// Type for memory share strategy
export type MemoryShareStrategy = (typeof MEMORY_SHARE_STRATEGY)[keyof typeof MEMORY_SHARE_STRATEGY];
