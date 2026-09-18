import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL(
  "../app/[locale]/agent-space/page.tsx",
  import.meta.url
);
const agentSpacePath = new URL(
  "../app/[locale]/agent-space/space.tsx",
  import.meta.url
);
const resourceCardPath = new URL(
  "../components/resource/ResourceCard.tsx",
  import.meta.url
);
const mineAgentPath = new URL(
  "../app/[locale]/agent-space/my-agent.tsx",
  import.meta.url
);
const reviewCenterPath = new URL(
  "../app/[locale]/agent-space/review-center.tsx",
  import.meta.url
);

test("agent repository displays up to twelve unified cards in four desktop columns", async () => {
  const [agentSpace, mineAgent, resourceCard] = await Promise.all([
    readFile(agentSpacePath, "utf8"),
    readFile(mineAgentPath, "utf8"),
    readFile(resourceCardPath, "utf8"),
  ]);

  assert.match(agentSpace, /const pageSize = columns \* rows;/);
  assert.match(
    agentSpace,
    /<ResourceCardGrid\s+items=\{listings\}\s+columns=\{columns\}/
  );
  assert.match(
    agentSpace,
    /import ResourceCard from "@\/components\/resource\/ResourceCard"/
  );
  assert.match(agentSpace, /<ResourceCard\s/);
  assert.match(agentSpace, /paginateItems=\{false\}/);
  assert.match(agentSpace, /onPageChange=\{setPage\}/);
  assert.match(
    agentSpace,
    /onClick=\{\(\) => setDetailListingId\(listing\.agent_repository_id\)\}/
  );
  assert.doesNotMatch(agentSpace, /key: "copy"/);
  assert.match(
    agentSpace,
    /title=\{[\s\S]*t\("agentRepository\.detail\.downloads"/
  );
  assert.match(
    agentSpace,
    /footer=\{[\s\S]*onClick=\{\(\) => setCopyListing\(listing\)\}/
  );
  assert.match(agentSpace, /footerLayout="inline"/);
  assert.match(agentSpace, /badge=\{[\s\S]*listing\.version_label/);
  assert.match(agentSpace, /Grid\.useBreakpoint\(\)/);
  assert.match(
    agentSpace,
    /const columns = screens\.xxl\s*\? 4\s*:\s*screens\.lg\s*\? 3/
  );
  assert.match(agentSpace, /gridHeight=\{/);
  assert.match(agentSpace, /descriptionLines=\{descriptionLines\}/);
  assert.match(agentSpace, /const pageBottomPadding = screens\.sm \? 40 : 32;/);
  assert.match(agentSpace, /viewportHeight - top - pageBottomPadding - 8/);
  assert.match(agentSpace, /const MIN_CARD_HEIGHT = 240;/);
  assert.match(resourceCard, /descriptionLines\?: number/);
  assert.match(resourceCard, /min-h-\[240px\]/);
  assert.match(resourceCard, /WebkitLineClamp: descriptionLines/);
  assert.match(mineAgent, /export function MyAgent/);
  assert.match(mineAgent, /<ResourceCardGrid[\s\S]*columns=\{4\}/);
});

test("agent-space tabs load same-level content components", async () => {
  const [page, reviewCenter] = await Promise.all([
    readFile(pagePath, "utf8"),
    readFile(reviewCenterPath, "utf8"),
  ]);
  assert.match(page, /import \{ AgentSpace \} from "\.\/space";/);
  assert.match(page, /import \{ MyAgent \} from "\.\/my-agent";/);
  assert.match(page, /import \{ ReviewCenter \} from "\.\/review-center";/);
  assert.match(page, /<AgentSpace/);
  assert.match(page, /<MyAgent/);
  assert.match(page, /<ReviewCenter/);
  assert.match(reviewCenter, /<ReviewAgentList/);
});

test("agent space uses full-width content with inset, left-aligned line tabs", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.doesNotMatch(page, /max-w-6xl/);
  assert.match(page, /(?:xl|2xl):px-16/);
  assert.match(
    page,
    /<TabsList[^>]*className="[^"]*justify-start[^"]*border-b[^"]*bg-transparent/
  );
  assert.doesNotMatch(page, /<TabsList[^>]*className="[^"]*mb-6/);
  assert.match(page, /data-\[state=active\]:border-primary/);
});
