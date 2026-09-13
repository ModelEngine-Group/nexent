// Persistent patch for @assistant-ui/react-generative-ui/dist/a2ui/convert.js
// Patches Chart and Table branches to resolve Nexus model format:
//   - chartType  → variant
//   - dataModel.valueList → data[] / rows[]
// Run this script after npm install to re-apply patches.
//   node scripts/patch-assistant-ui.js

const fs = require("fs");
const path = require("path");

const convertPath = path.join(
  __dirname,
  "..",
  "node_modules",
  "@assistant-ui",
  "react-generative-ui",
  "dist",
  "a2ui",
  "convert.js"
);

if (!fs.existsSync(convertPath)) {
  console.error("❌ convert.js not found at:", convertPath);
  process.exit(1);
}

let content = fs.readFileSync(convertPath, "utf-8");

// Skip if already patched
if (content.includes("resolveNexusChartData")) {
  console.log("✅ convert.js already patched");
  process.exit(0);
}

// Step 1: Add resolveNexusChartData helper before DEPTH_CAP
const helperFn = `
// Helper: resolve Nexus dataModel valueList into flat row objects.
// Nexus format: [{key: "data", valueList: [{key, valueString/Number/Boolean}, ...]}]
// with row boundaries detected by first key recurrence.
function resolveNexusChartData(dataSource) {
	if (!Array.isArray(dataSource) || dataSource.length === 0) return void 0;
	let valueList = null;
	for (const item of dataSource) {
		if (item && Array.isArray(item.valueList)) { valueList = item.valueList; break; }
	}
	if (!valueList || valueList.length === 0) return void 0;
	const orderedKeys = [];
	for (const item of valueList) {
		const k = String(item.key ?? "");
		if (k && !orderedKeys.includes(k)) orderedKeys.push(k);
	}
	if (orderedKeys.length === 0) return void 0;
	const rows = [];
	let currentRow = {};
	for (const item of valueList) {
		const k = String(item.key ?? "");
		if (!k) continue;
		const v = item.valueString !== void 0 ? item.valueString
			: item.valueNumber !== void 0 ? item.valueNumber
			: item.valueBoolean !== void 0 ? item.valueBoolean
			: item.value;
		if (k === orderedKeys[0] && Object.keys(currentRow).length > 0) {
			rows.push(currentRow);
			currentRow = {};
		}
		currentRow[k] = v;
	}
	if (Object.keys(currentRow).length > 0) rows.push(currentRow);
	return rows;
}
`;

content = content.replace(
  /\/\/#region src\/a2ui\/convert\.ts\nconst DEPTH_CAP = 32;/,
  `//#region src/a2ui/convert.ts${helperFn}const DEPTH_CAP = 32;`
);

// Step 2: Patch Chart branch
content = content.replace(
  `if (component === "Chart") {
\t\tconst variant = props["variant"] ?? "line";
\t\tconst data = props["data"];
\t\tconst series = props["series"];`,
  `if (component === "Chart") {
\t\tconst variant = props["variant"] ?? props["chartType"] ?? "line";
\t\tlet data = props["data"];
\t\tconst series = props["series"];
\t\t// Resolve data from dataSource if Nexus model uses valueList format
\t\tif (!Array.isArray(data) && dataSource != null) {
\t\t\tdata = resolveNexusChartData(dataSource);
\t\t}`
);

// Step 3: Patch Table branch
content = content.replace(
  `if (component === "Table") {
\t\tconst columns = props["columns"];
\t\tconst rows = props["rows"];`,
  `if (component === "Table") {
\t\tconst columns = props["columns"];
\t\tlet rows = props["rows"];
\t\t// Resolve rows from dataSource if Nexus model uses valueList format
\t\tif (!Array.isArray(rows) && dataSource != null) {
\t\t\trows = resolveNexusChartData(dataSource);
\t\t}`
);

fs.writeFileSync(convertPath, content, "utf-8");
console.log("✅ Patched convert.js — Chart & Table resolve from dataSource");
