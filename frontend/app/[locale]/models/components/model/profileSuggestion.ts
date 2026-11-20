// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AtomicProfileSummary } from "@/types/modelProfile";

export const normalizeProfileKeyword = (value: string) =>
  value
    .toLowerCase()
    .replace(/(glm)[\s/_-]*v(?=\d)/g, "$1")
    .replace(/[^a-z0-9]/g, "");

/** Exact identity wins; version-qualified prefixes produce an explicit approximate suggestion. */
export function suggestModelProfile(
  requestModelId: string,
  profiles: AtomicProfileSummary[]
): AtomicProfileSummary | undefined {
  const requested = normalizeProfileKeyword(requestModelId);
  if (!requested) return undefined;
  const ranked = profiles
    .map((profile) => {
      const id = normalizeProfileKeyword(
        profile.key.split("/").at(-1) ?? profile.key
      );
      const rawId = profile.key.split("/").at(-1) ?? profile.key;
      const identity = rawId
        .toLowerCase()
        .match(/([a-z]+?)[\s/_-]*v?(\d+)(?:[._-](\d{1,2})(?!\d))?/);
      const versions = identity
        ? Array.from(
            requestModelId
              .toLowerCase()
              .matchAll(
                new RegExp(
                  `${identity[1]}[\\s/_-]*v?(\\d+)(?:[._-](\\d{1,2})(?!\\d))?`,
                  "g"
                )
              )
          )
        : [];
      const sameVersion =
        identity &&
        versions.some(
          (match) => match[1] === identity[2] && match[2] === identity[3]
        );
      if (identity && versions.length && !sameVersion)
        return { profile, id, score: 0 };
      const names = [id, normalizeProfileKeyword(profile.name)];
      const exact = names.includes(requested);
      const contained = Math.max(
        0,
        ...names
          .filter(
            (name) =>
              (name.length >= 6 || sameVersion) && requested.includes(name)
          )
          .map((name) => name.length)
      );
      const partial =
        /[a-z]+\d/.test(requested) &&
        requested.length >= 6 &&
        names.some((name) => name.startsWith(requested));
      return {
        profile,
        id,
        score: exact
          ? 10000 + id.length
          : contained
            ? 1000 + contained
            : partial
              ? 100 - id.length
              : 0,
      };
    })
    .filter((entry) => entry.score > 0)
    .sort(
      (a, b) => b.score - a.score || a.profile.key.localeCompare(b.profile.key)
    );
  if (!ranked[0]) return undefined;
  // Duplicate exact identities from different sources need manual disambiguation.
  if (ranked[0].score === ranked[1]?.score && ranked[0].id === ranked[1]?.id)
    return undefined;
  return ranked[0].profile;
}

export function isApproximateProfile(
  requested: string,
  profile: AtomicProfileSummary
): boolean {
  const normalized = normalizeProfileKeyword(requested);
  return ![profile.key.split("/").at(-1) ?? profile.key, profile.name].some(
    (name) => normalizeProfileKeyword(name) === normalized
  );
}

export function matchesProfileKeywords(
  query: string,
  profile: AtomicProfileSummary
): boolean {
  const haystack = normalizeProfileKeyword(
    `${profile.key} ${profile.name} ${profile.family ?? ""}`
  );
  return query
    .trim()
    .split(/\s+/)
    .every((token) => haystack.includes(normalizeProfileKeyword(token)));
}
