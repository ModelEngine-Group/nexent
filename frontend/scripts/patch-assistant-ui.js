// Persistent patch for @assistant-ui/react-generative-ui/dist/a2ui/convert.js
// Patches Chart, Table, and TodoList branches to resolve Nexus model format:
//   - chartType  → variant
//   - dataModel.valueList → data[] / rows[]
//   - TodoList: add to SUPPORTED_COMPONENTS + mappedProps pass-through
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

// Step 4: Add "TodoList" to SUPPORTED_COMPONENTS
content = content.replace(
  `"Carousel"\n]);`,
  `"Carousel",\n\t"TodoList" // custom client-side interactive component\n]);`
);

// Step 5: Add TodoList case to mappedProps (before the closing of mappedProps fn)
content = content.replace(
  `\tif (component === "RadioGroup") {\n\t\tconst options = props["options"] ?? props["choices"];\n\t\treturn {\n\t\t\t$type: "RadioGroup",\n\t\t\t...Array.isArray(options) ? { options } : {},\n\t\t\t...label !== void 0 ? { label } : {},\n\t\t\t...name !== void 0 ? { name } : {}\n\t\t};\n\t}\n};`,
  `\tif (component === "RadioGroup") {\n\t\tconst options = props["options"] ?? props["choices"];\n\t\treturn {\n\t\t\t$type: "RadioGroup",\n\t\t\t...Array.isArray(options) ? { options } : {},\n\t\t\t...label !== void 0 ? { label } : {},\n\t\t\t...name !== void 0 ? { name } : {}\n\t\t};\n\t}\n\tif (component === "TodoList") {\n\t\t// Custom client-side interactive component — pass items/placeholder through.\n\t\t// No dataModel binding; items are always inline [{id, text, done}].\n\t\treturn {\n\t\t\t$type: "TodoList",\n\t\t\t...Array.isArray(props["items"]) ? { items: props["items"] } : {},\n\t\t\t...typeof props["placeholder"] === "string" ? { placeholder: props["placeholder"] } : {}\n\t\t};\n\t}\n};`
);

fs.writeFileSync(convertPath, content, "utf-8");
console.log("✅ Patched convert.js — TodoList support added");
