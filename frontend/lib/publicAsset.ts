import { withBasePath } from "@/lib/basePath";

export function publicAsset(path: string): string {
  return withBasePath(path);
}
