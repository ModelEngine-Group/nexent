import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(
  frontendRoot,
  "../contracts/nl2agent-card.schema.json"
);
const targetPath = resolve(
  frontendRoot,
  "contracts/generated/nl2agent-card.schema.json"
);
const source = await readFile(sourcePath, "utf8");

if (process.argv.includes("--check")) {
  const target = await readFile(targetPath, "utf8").catch(() => "");
  if (target !== source) {
    throw new Error(
      "Generated NL2AGENT card schema is out of date. Run pnpm contracts:generate."
    );
  }
} else {
  await mkdir(dirname(targetPath), { recursive: true });
  await writeFile(targetPath, source, "utf8");
}
