import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const markdownTextPath = new URL(
  "../app/[locale]/newchat/ui/markdown-text.tsx",
  import.meta.url
);

test("renders GFM strikethrough content as plain text in newchat", async () => {
  const markdownText = await readFile(markdownTextPath, "utf8");

  assert.match(markdownText, /remarkPlugins=\{\[remarkGfm, remarkCite\]\}/);
  assert.match(
    markdownText,
    /del:\s*\(\{\s*children,\s*\.\.\.props\s*\}\)\s*=>\s*\(?\s*<span[\s\S]*>\s*\{children\}\s*<\/span>/
  );
});
