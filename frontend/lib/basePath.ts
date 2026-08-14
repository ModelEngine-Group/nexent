import { BASE_PATH } from "@/base-path.mjs";

export { BASE_PATH };

export function withBasePath(path: string): string {
  if (!path.startsWith("/") || !BASE_PATH || path === BASE_PATH || path.startsWith(`${BASE_PATH}/`)) {
    return path;
  }

  return `${BASE_PATH}${path}`;
}

export function withoutBasePath(path: string): string {
  if (!BASE_PATH || (path !== BASE_PATH && !path.startsWith(`${BASE_PATH}/`))) {
    return path;
  }

  return path.slice(BASE_PATH.length) || "/";
}
