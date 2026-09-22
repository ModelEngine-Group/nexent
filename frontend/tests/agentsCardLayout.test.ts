import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const agentsPagePath = new URL(
  "../app/[locale]/agents/page.tsx",
  import.meta.url
);

test("renders the Agents picker with responsive rows and a create card", async () => {
  const page = await readFile(agentsPagePath, "utf8");

  assert.match(
    page,
    /import \{[\s\S]*Col[\s\S]*Grid[\s\S]*Row[\s\S]*\} from "antd"/
  );
  assert.match(page, /CreateResourceCard/);
  assert.match(
    page,
    /xs=\{24\}[\s\S]*sm=\{12\}[\s\S]*xl=\{8\}[\s\S]*xxl=\{6\}/
  );
  assert.match(page, /agentRepository\.page\.tab\.mine/);
  assert.match(
    page,
    /<CreateResourceCard[\s\S]*title=\{t\("agentConfig\.button\.new"\)\}/
  );
});
