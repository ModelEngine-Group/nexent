import type { Agent } from "@/types/agentConfig";

/** Core selection never rewrites saved policies or resource bindings. */
export function compatibleCorePatch<T extends Partial<Agent>>(
  _current: Partial<Agent> | null,
  patch: T
): T & Partial<Agent> {
  return patch;
}
