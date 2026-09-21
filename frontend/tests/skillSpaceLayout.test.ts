import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const route = new URL("../app/[locale]/skill-space/", import.meta.url);
const mcpPage = new URL("../app/[locale]/mcp-space/page.tsx", import.meta.url);
const repositoryView = new URL("components/RepositoryView.tsx", route);
const repositoryCard = new URL("components/SkillRepositoryCard.tsx", route);
const mineView = new URL("components/MineSkillsView.tsx", route);
const skillSpace = new URL("skill-space.tsx", route);
const mySkill = new URL("my-skill.tsx", route);
const tagFilterPopover = new URL(
  "../components/tag/TagFilterPopover.tsx",
  import.meta.url
);

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

test("skill space uses Agent repository default component radius", async () => {
  const page = await readFile(new URL("page.tsx", route), "utf8");

  assert.doesNotMatch(page, /borderRadius\s*:/);
});

test("skill repository delegates visible pagination to ResourceCardGrid", async () => {
  const view = await readFile(repositoryView, "utf8");

  assert.match(
    view,
    /<ResourceCardGrid[\s\S]*page=\{page\}[\s\S]*total=\{total\}[\s\S]*onPageChange=\{onPageChange\}[\s\S]*paginateItems=\{false\}/
  );
  assert.doesNotMatch(view, /<PaginationBar/);
});

test("skill repository cards open on click and keep Copy as the compact footer action", async () => {
  const [view, card] = await Promise.all([
    readFile(repositoryView, "utf8"),
    readFile(repositoryCard, "utf8"),
  ]);

  assert.match(view, /<Button\s+type="text"\s+size="small"[\s\S]*icon=\{<Copy/);
  assert.doesNotMatch(view, /skillRepository\.common\.detail/);
  assert.match(card, /footerLayout="inline"/);
  assert.match(card, /onClick=\{onDetailClick\}/);
  assert.match(card, /headerActions=\{[\s\S]*Download/);
  assert.match(card, /actions=\{[\s\S]*MoreHorizontal/);
  assert.match(card, /min-h-7/);
});

test("my skill cards move shared status beside More and keep only the lower-right edit or view action", async () => {
  const view = await readFile(mineView, "utf8");

  assert.doesNotMatch(view, /\bHub\b/);
  assert.doesNotMatch(view, /getSkillSourceLabel/);
  assert.match(
    view,
    /headerActions=\{[\s\S]*MoreHorizontal[\s\S]*getSkillRepositoryStatusLabel/
  );
  assert.doesNotMatch(view, /getApplyButtonLabel/);
  assert.match(view, /footerLayout="inline"/);
});

test("skill grids share Agent-style adaptive dimensions and default-height controls", async () => {
  const [repository, mine, repositoryContainer, mineContainer, tagFilter] =
    await Promise.all([
      readFile(skillSpace, "utf8"),
      readFile(mySkill, "utf8"),
      readFile(repositoryView, "utf8"),
      readFile(mineView, "utf8"),
      readFile(tagFilterPopover, "utf8"),
    ]);

  for (const source of [repository, mine]) {
    assert.match(source, /Grid\.useBreakpoint\(\)/);
    assert.match(source, /const columns = screens\.xxl/);
    assert.match(source, /const pageSize = columns \* rows/);
  }
  for (const source of [repositoryContainer, mineContainer]) {
    assert.match(
      source,
      /columns=\{columns\}[\s\S]*rows=\{rows\}[\s\S]*gridHeight=\{gridHeight\}/
    );
    assert.match(
      source,
      /page=\{page\}[\s\S]*total=\{total\}[\s\S]*onPageChange=\{onPageChange\}/
    );
    assert.doesNotMatch(source, /<PaginationBar/);
  }
  assert.doesNotMatch(tagFilter, /className="h-11"/);
});

test("skill feedback matches Agent search controls, exposes tags, and shows repository authors", async () => {
  const [repository, mine, card] = await Promise.all([
    readFile(repositoryView, "utf8"),
    readFile(mineView, "utf8"),
    readFile(repositoryCard, "utf8"),
  ]);

  assert.match(
    repository,
    /<TagFilterPopover[\s\S]*onChange=\{onTagPredicatesChange\}\s*\/>/
  );
  assert.match(repository, /className="rounded-xl"/);
  assert.doesNotMatch(mine, /skillRepository\.mine\.createSkill/);
  assert.match(mine, /<Popover[\s\S]*repository\.tagFilter\.button/);
  assert.match(mine, /className="rounded-xl"/);
  assert.match(card, /min-h-7/);
  assert.match(
    card,
    /listing\.author\?\.trim\(\) \|\| listing\.submitted_by\?\.trim\(\)/
  );
});
