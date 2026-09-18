import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const route = new URL("../app/[locale]/skill-space/", import.meta.url);
const mcpPage = new URL("../app/[locale]/mcp-space/page.tsx", import.meta.url);

test("skill space keeps tab content and actions in three sibling components", async () => {
  const page = await readFile(new URL("page.tsx", route), "utf8");
  const files = await readdir(route);
  for (const [file, component] of [
    ["skill-space.tsx", "SkillSpace"],
    ["my-skill.tsx", "MySkill"],
    ["review-center.tsx", "ReviewCenter"],
  ]) {
    assert.ok(files.includes(file), `${file} exists`);
    assert.match(page, new RegExp(`<${component}\\b`));
  }
  assert.doesNotMatch(page, /<RepositoryView|<MineSkillsView|<ReviewSkillList/);
  assert.doesNotMatch(page, /<Modal|<SkillBuildModal|<SkillDetailModal/);
  assert.doesNotMatch(
    page,
    /useCreateSkillRepositoryListing|useUpdateSkillRepositoryStatus/
  );
});

test("skill space uses the same page inset and tab treatment as MCP space", async () => {
  const [page, mcp] = await Promise.all([
    readFile(new URL("page.tsx", route), "utf8"),
    readFile(mcpPage, "utf8"),
  ]);
  for (const pattern of [
    /px-4 py-8 sm:px-6 sm:py-10 xl:px-16/,
    /justify-start[^\"]*border-b[^\"]*bg-transparent/,
    /data-\[state=active\]:border-primary/,
  ]) {
    assert.match(mcp, pattern);
    assert.match(page, pattern);
  }
  assert.doesNotMatch(page, /max-w-6xl/);
});
