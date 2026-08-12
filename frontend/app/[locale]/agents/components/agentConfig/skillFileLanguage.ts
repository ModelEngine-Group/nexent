/**
 * Mapping from Skill file extensions / filenames to Shiki language IDs.
 *
 * Shiki accepts any TextMate grammar registered in the bundled language set.
 * Keep the mapping narrow and predictable: it must cover the file types the
 * Skill creator and editor commonly produce, fall back to plain text for
 * anything else, and never invent grammars that are not actually loaded.
 */

export const UNKNOWN_LANGUAGE = "text";

/**
 * Files that should not be treated as code even when they have a recognised
 * extension. Markdown already has its own renderer; we keep this guard so a
 * future caller cannot accidentally route `.md` through the code highlighter.
 */
const NON_CODE_EXTENSIONS = new Set(["md", "markdown", "mdx"]);

/**
 * Extension -> Shiki language ID. Lower-cased keys, dot is required for
 * extension entries. Filename-only entries (Dockerfile, Makefile, etc.) are
 * handled separately below.
 */
const EXTENSION_LANGUAGE_MAP: Record<string, string> = {
  ts: "typescript",
  tsx: "tsx",
  mts: "typescript",
  cts: "typescript",
  js: "javascript",
  jsx: "jsx",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  jsonc: "jsonc",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  ini: "ini",
  conf: "ini",
  properties: "ini",
  xml: "xml",
  html: "html",
  htm: "html",
  vue: "vue",
  svelte: "svelte",
  css: "css",
  scss: "scss",
  sass: "sass",
  less: "less",
  postcss: "postcss",
  py: "python",
  pyi: "python",
  pyw: "python",
  rb: "ruby",
  rs: "rust",
  go: "go",
  java: "java",
  kt: "kotlin",
  kts: "kotlin",
  swift: "swift",
  m: "objectivec",
  mm: "objectivecpp",
  cs: "csharp",
  cpp: "cpp",
  c: "c",
  h: "c",
  hpp: "cpp",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  fish: "fish",
  ps1: "powershell",
  bat: "batch",
  cmd: "batch",
  sql: "sql",
  graphql: "graphql",
  gql: "graphql",
  proto: "protobuf",
  dockerfile: "dockerfile",
  makefile: "makefile",
  cmake: "cmake",
  diff: "diff",
  patch: "diff",
  tex: "latex",
  rst: "rst",
  log: "text",
  txt: "text",
  env: "dotenv",
};

/**
 * Filenames (lower-cased, without leading directory) that imply a specific
 * language regardless of extension.
 */
const FILENAME_LANGUAGE_MAP: Record<string, string> = {
  dockerfile: "dockerfile",
  containerfile: "dockerfile",
  makefile: "makefile",
  "gnu makefile": "makefile",
  cmakelists: "cmake",
  rakefile: "ruby",
  gemfile: "ruby",
  procfile: "procfile",
};

/**
 * Extract the trailing extension (without the dot) from a Skill file path.
 * Returns an empty string when the basename has no dot or is dotfile-only.
 */
export function getFileExtension(filePath: string): string {
  if (!filePath) return "";
  const fileName = filePath.split("/").pop() || filePath;
  const dotIndex = fileName.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex === fileName.length - 1) {
    return "";
  }
  return fileName.slice(dotIndex + 1).toLowerCase();
}

/**
 * Resolve the basename of a Skill file path. Always returns the last segment.
 */
function getBaseName(filePath: string): string {
  if (!filePath) return "";
  const segments = filePath.split("/").filter(Boolean);
  return segments[segments.length - 1] || filePath;
}

/**
 * Resolve the language ID for a Skill file. Returns `UNKNOWN_LANGUAGE`
 * when the path is empty, the extension is not mapped, the extension is
 * explicitly excluded (Markdown), or the filename has no usable hint.
 *
 * The function is pure so callers can memoise it alongside React state.
 */
export function resolveLanguageFromPath(filePath: string): string {
  if (!filePath) return UNKNOWN_LANGUAGE;

  const baseName = getBaseName(filePath).toLowerCase();
  if (baseName && FILENAME_LANGUAGE_MAP[baseName]) {
    return FILENAME_LANGUAGE_MAP[baseName];
  }

  const extension = getFileExtension(filePath);
  if (!extension) return UNKNOWN_LANGUAGE;
  if (NON_CODE_EXTENSIONS.has(extension)) return UNKNOWN_LANGUAGE;

  return EXTENSION_LANGUAGE_MAP[extension] ?? UNKNOWN_LANGUAGE;
}

/**
 * Resolve a language ID with an explicit override. When `explicitLanguage` is
 * truthy it wins, otherwise we fall back to the path-based resolution. Empty
 * strings are treated as "use the path" to match how callers compose props.
 */
export function resolveLanguage(
  filePath: string,
  explicitLanguage?: string | null
): string {
  if (explicitLanguage && explicitLanguage.trim()) {
    return explicitLanguage.trim().toLowerCase();
  }
  return resolveLanguageFromPath(filePath);
}

/**
 * Whether the renderer should treat the file as code. Markdown is always
 * rendered through the Markdown pipeline, never through Shiki.
 */
export function isCodeFile(filePath: string): boolean {
  return resolveLanguageFromPath(filePath) !== UNKNOWN_LANGUAGE;
}
