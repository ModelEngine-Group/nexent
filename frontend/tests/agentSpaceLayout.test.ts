import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL(
  "../app/[locale]/agent-space/page.tsx",
  import.meta.url
);
const cardPath = new URL(
  "../app/[locale]/agent-space/components/AgentRepositoryCard.tsx",
  import.meta.url
);
const agentSpacePath = new URL(
  "../app/[locale]/agent-space/agent-space.tsx",
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
  const [page, card, agentSpace, mineAgent] = await Promise.all([
    readFile(pagePath, "utf8"),
    readFile(cardPath, "utf8"),
    readFile(agentSpacePath, "utf8"),
    readFile(mineAgentPath, "utf8"),
  ]);

  assert.match(page, /const REPOSITORY_PAGE_SIZE = 12;/);
  assert.match(
    agentSpace,
    /<ResourceCardGrid\s+items=\{listings\}\s+columns=\{4\}/
  );
  assert.match(
    card,
    /import ResourceCard from "@\/components\/resource\/ResourceCard"/
  );
  assert.match(card, /<ResourceCard\s/);
  assert.match(mineAgent, /export function MyAgent/);
  assert.match(mineAgent, /<ResourceCardGrid[\s\S]*columns=\{4\}/);
});

test("agent-space tabs load same-level content components", async () => {
  const [page, reviewCenter] = await Promise.all([
    readFile(pagePath, "utf8"),
    readFile(reviewCenterPath, "utf8"),
  ]);
  assert.match(page, /import \{ AgentSpace \} from "\.\/agent-space";/);
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
  assert.match(page, /data-\[state=active\]:border-primary/);
});
