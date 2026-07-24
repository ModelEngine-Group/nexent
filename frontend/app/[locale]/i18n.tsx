import i18n, { ThirdPartyModule } from "i18next";
import { initReactI18next } from "react-i18next";

const resources = {
  en: {
    common: {},
  },
  zh: {
    common: {},
  },
}

const resourcesCustom = {
  en: {
    custom: {},
    replacemenKeyArr: [],
  },
  zh: {
    custom: {},
    replacemenKeyArr: [],
  },
}

export const loadLocaleMessages = async (locale: string) => {
  try {
    const localePath = locale === 'zh' ? 'zh' : 'en';
    const response = await fetch(`/locales/${localePath}/common.json`);
    const common = await response.json();
    if (resources[localePath]) {
      resources[localePath].common = common;
    }

    const responseCustom = await fetch(`/locales/${localePath}/custom.json`);
    const commonCustom = await responseCustom.json();
    if (resourcesCustom[localePath]) {
      resourcesCustom[localePath].custom = commonCustom;
      resourcesCustom[localePath].replacemenKeyArr = Object.entries(commonCustom).map(([key, value]) => {
        const item = { pattern: key, str: value };
        return item;
      }) as any;
    }
    return { resourcesCustom, resources };
  } catch (error) {
    console.log(`Failed to load locale ${locale}:`, error)
  } finally {
    return { resourcesCustom, resources };
  }
}

const parseI18NStrFunc = (str: string, lang: string): any => {
  if (!str) {
    return '';
  }

  const replacementKeyArr: any[] = lang === 'en' ? resourcesCustom.en.replacemenKeyArr : resourcesCustom.zh.replacemenKeyArr;
  let newStr = String(str);
   replacementKeyArr.forEach(replacePair => {
    const patternKey= `{${replacePair.pattern}}`;
    const replaceStr = replacePair.str;
    newStr = newStr.replace(new RegExp(patternKey, 'g'), replaceStr);
  })

  return newStr;
}

const deepProcessStr = (data: any, handler = (v: string) => v): any => {
  if (Array.isArray(data)) {
    return data.map(item => deepProcessStr(item, handler))
  }

  if (typeof data === 'object' && data !== null) {
    const newObj: any = {};
    for(const key in data) {
      newObj[key] = deepProcessStr(data[key], handler)
    }
    return newObj;
  }
  return handler(data);
}

const parseI18nFunc = (strData: any, lang: string) => {
  if (strData instanceof Object) {

    return deepProcessStr(strData, (v): string => parseI18NStrFunc(v, lang));
  }
  return parseI18NStrFunc(strData, lang);
}
const  processI18n: ThirdPartyModule = {
  type: '3rdParty',
  init(i18next) {
    const originalT = i18next.t.bind(i18next);
    (i18next as any).t = (key: string, opts: any) => {
      const originData = originalT(key, opts);
      return parseI18nFunc(originData, i18next.language);
    }
  }
}


if (!i18n.isInitialized) {
  i18n.use(processI18n).use(initReactI18next).init({
    resources: resources,
    lng: "zh", // default language
    fallbackLng: "en",
    ns: ["common"],
    defaultNS: "common",
    interpolation: {
      escapeValue: false,
    },
    react: {
      useSuspense: false,
    },
  });
}

export default i18n;
