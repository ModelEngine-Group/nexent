// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Folder paths in the AIDP knowledge base are relative to the knowledge base
 * root and always start with `/`. These helpers keep the UI from hand-building
 * paths in several places, which is how a missing or doubled slash would turn
 * into a confusing upstream 404.
 */

export const normalizeFolderPath = (path?: string | null): string => {
  const value = (path || "/").trim().replace(/\\/g, "/");
  if (!value || value === "/") return "/";
  const normalized = `/${value.split("/").filter(Boolean).join("/")}`;
  return normalized || "/";
};

export const joinFolderPath = (parent: string, name: string): string => {
  const normalizedParent = normalizeFolderPath(parent);
  const normalizedName = name.trim().replace(/^\/+|\/+$/g, "");
  if (!normalizedName) return normalizedParent;
  return normalizedParent === "/"
    ? `/${normalizedName}`
    : `${normalizedParent}/${normalizedName}`;
};

export const parentFolderPath = (path: string): string => {
  const normalized = normalizeFolderPath(path);
  if (normalized === "/") return "/";
  const parent = normalized.slice(0, normalized.lastIndexOf("/"));
  return parent || "/";
};

export const folderNameFromPath = (path: string): string => {
  const normalized = normalizeFolderPath(path);
  if (normalized === "/") return "/";
  return normalized.slice(normalized.lastIndexOf("/") + 1);
};

/** Ancestor folders of `path`, root first and excluding `path` itself. */
export const folderAncestorPaths = (path: string): string[] => {
  const normalized = normalizeFolderPath(path);
  if (normalized === "/") return [];
  const parts = normalized.split("/").filter(Boolean);
  const ancestors = ["/"];
  let current = "";
  for (const part of parts.slice(0, -1)) {
    current += `/${part}`;
    ancestors.push(current);
  }
  return ancestors;
};

/** Breadcrumb segments from the root down to `path`. */
export const folderPathSegments = (
  path: string
): Array<{ path: string; label: string }> => {
  const normalized = normalizeFolderPath(path);
  if (normalized === "/") return [];
  const parts = normalized.split("/").filter(Boolean);
  let current = "";
  return parts.map((part) => {
    current += `/${part}`;
    return { path: current, label: part };
  });
};

/** True when `path` is `root` itself or lies below it. */
export const isPathEqualOrInside = (path: string, root: string): boolean => {
  const normalizedPath = normalizeFolderPath(path);
  const normalizedRoot = normalizeFolderPath(root);
  if (normalizedRoot === "/") return true;
  return (
    normalizedPath === normalizedRoot ||
    normalizedPath.startsWith(`${normalizedRoot}/`)
  );
};

/** Replace a moved/renamed folder prefix inside the current path. */
export const replaceFolderPrefix = (
  path: string,
  oldPrefix: string,
  newPrefix: string
): string => {
  const normalizedPath = normalizeFolderPath(path);
  const normalizedOld = normalizeFolderPath(oldPrefix);
  if (normalizedPath === normalizedOld) return normalizeFolderPath(newPrefix);
  if (normalizedPath.startsWith(`${normalizedOld}/`)) {
    return `${normalizeFolderPath(newPrefix)}${normalizedPath.slice(normalizedOld.length)}`;
  }
  return normalizedPath;
};
