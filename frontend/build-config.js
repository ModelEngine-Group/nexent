import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BUILT_IN_LOCALES_CONFIG_DIR = path.resolve(__dirname, "./public/locales");
const LOCALES_CONFIG_DIR = process.env.PROJECT_CONFIG_DIR
  ? path.resolve(process.env.PROJECT_CONFIG_DIR, "locales")
  : BUILT_IN_LOCALES_CONFIG_DIR;

const defaultSize = 10;

let fileUploadSizeLimit = process.env.FILE_UPLOAD_SIZE_LIMIT || defaultSize;

if (!Number.isInteger(Number(fileUploadSizeLimit))) {
  fileUploadSizeLimit = defaultSize;
} else {
  fileUploadSizeLimit = Math.min(100, Math.max(10, fileUploadSizeLimit));
}

export function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export function readLocaleConfig(lang) {
  try {
    const fileName = "custom.json";
    const locale = lang === "zh" ? "zh" : "en";
    const filepath = path.join(LOCALES_CONFIG_DIR, locale, fileName);
    const fallbackPath = path.join(
      BUILT_IN_LOCALES_CONFIG_DIR,
      locale,
      fileName
    );
    const selectedPath = fs.existsSync(filepath) ? filepath : fallbackPath;
    if (!fs.existsSync(selectedPath)) {
      return {};
    }
    const data = JSON.parse(fs.readFileSync(selectedPath, "utf-8"));
    return data;
  } catch (error) {
    console.log(error.message);
    return {};
  }
}

export function saveLocaleConfig(fileData, lang) {
  const fileName = "custom.json";
  const filepath = path.join(LOCALES_CONFIG_DIR, lang, fileName);
  ensureDir(path.dirname(filepath));
  fs.writeFileSync(filepath, fileData, "utf-8");
  return fileName;
}

const langMap = ["zh", "en"];

for (const lang of langMap) {
  const customData = readLocaleConfig(lang);
  customData["FILE_UPLOAD_SIZE_LIMIT"] = fileUploadSizeLimit;
  saveLocaleConfig(JSON.stringify(customData, null, 2), lang);
}
