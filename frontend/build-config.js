import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const LOCALES_CONFIG_DIR = path.resolve(__dirname, "./public/locales");

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

function localeConfigPath(lang, baseDir) {
  return path.join(baseDir, lang === "zh" ? "zh" : "en", "custom.json");
}

export function atomicWriteFile(filepath, fileData) {
  ensureDir(path.dirname(filepath));
  const tempPath = path.join(
    path.dirname(filepath),
    `.${path.basename(filepath)}.${process.pid}.${randomUUID()}.tmp`
  );
  let fileDescriptor;
  try {
    fileDescriptor = fs.openSync(tempPath, "w");
    fs.writeFileSync(fileDescriptor, fileData, "utf-8");
    fs.fsyncSync(fileDescriptor);
    fs.closeSync(fileDescriptor);
    fileDescriptor = undefined;
    fs.renameSync(tempPath, filepath);
  } catch (error) {
    if (fileDescriptor !== undefined) {
      fs.closeSync(fileDescriptor);
    }
    if (fs.existsSync(tempPath)) {
      fs.unlinkSync(tempPath);
    }
    throw error;
  }
}

export function readLocaleConfig(
  lang,
  baseDir = LOCALES_CONFIG_DIR,
  fallbackDir
) {
  try {
    let filepath = localeConfigPath(lang, baseDir);
    if (!fs.existsSync(filepath) && fallbackDir) {
      filepath = localeConfigPath(lang, fallbackDir);
    }
    if (!fs.existsSync(filepath)) {
      return {};
    }
    const data = JSON.parse(fs.readFileSync(filepath, "utf-8"));
    return data;
  } catch (error) {
    console.log(error.message);
    return {};
  }
}

export function saveLocaleConfig(fileData, lang, baseDir = LOCALES_CONFIG_DIR) {
  const filepath = localeConfigPath(lang, baseDir);
  atomicWriteFile(filepath, fileData);
  return "custom.json";
}

const langMap = ["zh", "en"];

for (const lang of langMap) {
  const customData = readLocaleConfig(lang);
  customData["FILE_UPLOAD_SIZE_LIMIT"] = fileUploadSizeLimit;
  saveLocaleConfig(JSON.stringify(customData, null, 2), lang);
}
