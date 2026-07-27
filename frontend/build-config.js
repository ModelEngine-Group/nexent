const fs = require("node:fs");
const path = require("path");

const LOCALES_CONFIG_DIR = path.resolve(__dirname, "./public/locales");

const defaultSize = 10;

let fileUploadSizeLimit = process.env.FILE_UPLOAD_SIZE_LIMIT || defaultSize;

if (!Number.isInteger(Number(fileUploadSizeLimit))) {
    fileUploadSizeLimit = defaultSize;
} else {

    fileUploadSizeLimit = fileUploadSizeLimit > 100 ? 100 : fileUploadSizeLimit;
    fileUploadSizeLimit = fileUploadSizeLimit < 10 ? 10 : fileUploadSizeLimit;
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function readLocaleConfig(lang) {
  try {
    const fileName = 'custom.json';
    const filepath = path.join(LOCALES_CONFIG_DIR, lang === 'zh' ? 'zh' : 'en', fileName);
    if (!fs.existsSync(filepath)) {
      return {};
    }
    const data = JSON.parse(fs.readFileSync(filepath, "utf-8"))
    return data;
  } catch (error) {
    console.log(error.message)
  }
}

function saveLocaleConfig(fileData, lang) {
  ensureDir(LOCALES_CONFIG_DIR);
  const fileName = 'custom.json';
  const filepath = path.join(LOCALES_CONFIG_DIR, lang, fileName);
  fs.writeFileSync(filepath, fileData, "utf-8");
  return fileName;
}

const langMap = ['zh', 'en'];

for(const index in langMap) {
    const lang = langMap[index];
    const customData = readLocaleConfig(lang);
    customData["FILE_UPLOAD_SIZE_LIMIT"] = fileUploadSizeLimit;
    saveLocaleConfig(JSON.stringify(customData, null, 2), lang);
}