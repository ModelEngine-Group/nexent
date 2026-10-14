/**
 * Module-level cache for tag assignment reads.
 *
 * List pages mount one ResourceTagChips per row, and every mount used to fire
 * its own GET /tag-libraries/assignments request. With many rows the browser
 * connection pool serialized the requests and the page stalled. This cache
 * shares in-flight promises (so concurrent mounts for the same resource issue
 * one request) and keeps values for a short TTL. Writes invalidate affected
 * keys immediately.
 */

import type { TagAssignment } from "@/types/tagManagement";

const DEFAULT_TTL_MS = 30_000;

interface AssignmentCacheEntry {
  promise: Promise<TagAssignment>;
  expiresAt: number;
}

export interface AssignmentCacheKey {
  resourceType: string;
  resourceId: string;
  query: string;
}

export function mergeAssignmentCacheKey(
  resourceType: string,
  resourceId: string,
  query: string
): AssignmentCacheKey {
  return { resourceType, resourceId, query };
}

const assignmentCache = new Map<string, AssignmentCacheEntry>();

function keyFor(key: AssignmentCacheKey): string {
  return `${key.resourceType}::${key.resourceId}::${key.query}`;
}

function isFresh(entry: AssignmentCacheEntry, now: number): boolean {
  return entry.expiresAt > now;
}

export function getCachedAssignmentPromise(
  key: AssignmentCacheKey,
  loader: () => Promise<TagAssignment>,
  ttlMs: number = DEFAULT_TTL_MS
): Promise<TagAssignment> {
  const cacheKey = keyFor(key);
  const now = Date.now();
  const existing = assignmentCache.get(cacheKey);
  if (existing && isFresh(existing, now)) {
    return existing.promise;
  }
  const fresh: AssignmentCacheEntry = {
    promise: loader(),
    expiresAt: now + ttlMs,
  };
  fresh.promise = fresh.promise.catch((error: unknown) => {
    assignmentCache.delete(cacheKey);
    throw error;
  });
  assignmentCache.set(cacheKey, fresh);
  return fresh.promise;
}

export function clearCachedAssignmentsByResource(
  resourceType: string,
  resourceId: string
): void {
  const prefix = `${resourceType}::${resourceId}::`;
  for (const key of assignmentCache.keys()) {
    if (key.startsWith(prefix)) assignmentCache.delete(key);
  }
}

export function clearAssignmentCache(): void {
  assignmentCache.clear();
}
