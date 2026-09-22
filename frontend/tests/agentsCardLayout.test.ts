import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const agentsPagePath = new URL(
  "../app/[locale]/agents/page.tsx",
  import.meta.url
);

test("renders the Agents picker with responsive rows and a create card", async () => {
  const page = await readFile(agentsPagePath, "utf8");

  assert.match(page, /import \{[^}]*Col[^}]*Grid[^}]*Row[^}]*\} from "antd"/s);
  assert.match(page, /CreateResourceCard/);
  assert.match(page, /xs=\{24\}\s+sm=\{12\}\s+xl=\{8\}\s+xxl=\{6\}/s);
  assert.match(page, /agentRepository\.page\.tab\.mine/);
  assert.match(
    page,
    /<CreateResourceCard[\s\S]*title=\{t\("agentConfig\.button\.new"\)\}/
  );
});
