import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";
import { format } from "prettier";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(
  frontendRoot,
  "../contracts/nl2agent-card.schema.json"
);
const targetPath = resolve(
  frontendRoot,
  "contracts/generated/nl2agent-card.schema.json"
);
const repositoryRoot = resolve(frontendRoot, "..");
const openapiSourcePath = resolve(
  repositoryRoot,
  "contracts/nl2agent-openapi.json"
);
const apiTypesTargetPath = resolve(
  frontendRoot,
  "contracts/generated/nl2agent-api.ts"
);
const backendPythonCandidates = [
  process.env.NEXENT_BACKEND_PYTHON,
  resolve(repositoryRoot, "backend/.venv/Scripts/python.exe"),
  resolve(repositoryRoot, "backend/.venv/bin/python"),
].filter(Boolean);
const backendPython = backendPythonCandidates.find(existsSync);
if (!backendPython) {
  throw new Error(
    "Backend virtualenv Python is required for contract generation."
  );
}
const checkMode = process.argv.includes("--check");
const exportArguments = [
  resolve(repositoryRoot, "backend/scripts/export_nl2agent_openapi.py"),
  "--output",
  openapiSourcePath,
  ...(checkMode ? ["--check"] : []),
];
const exportResult = spawnSync(backendPython, exportArguments, {
  cwd: repositoryRoot,
  encoding: "utf8",
});
if (exportResult.status !== 0) {
  throw new Error(
    exportResult.stderr ||
      exportResult.stdout ||
      "Failed to export NL2AGENT OpenAPI."
  );
}
const source = await readFile(sourcePath, "utf8");

if (checkMode) {
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
const openapiSource = JSON.parse(await readFile(openapiSourcePath, "utf8"));
const apiTypes = await format(
  astToString(await openapiTS(openapiSource, { defaultNonNullable: false })),
  { parser: "typescript" }
);
if (checkMode) {
  const target = await readFile(apiTypesTargetPath, "utf8").catch(() => "");
  if (target !== apiTypes) {
    throw new Error(
      "Generated NL2AGENT API types are out of date. Run pnpm contracts:generate."
    );
  }
} else {
  await mkdir(dirname(apiTypesTargetPath), { recursive: true });
  await writeFile(apiTypesTargetPath, apiTypes, "utf8");
}
