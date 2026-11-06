// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n, { ThirdPartyModule } from "i18next";
import { initReactI18next } from "react-i18next";
import { withBasePath } from "@/lib/basePath";
import log from "@/lib/logger";

type LocalePath = "en" | "zh";
type ReplacementEntry = { pattern: string; str: string };
type CustomLocaleResources = {
  custom: Record<string, string>;
  replacemenKeyArr: ReplacementEntry[];
};

const resources = {
  en: {
    common: {},
  },
  zh: {
    common: {},
  },
}

export const resourcesCustom: Record<LocalePath, CustomLocaleResources> = {
  en: {
    custom: {},
    replacemenKeyArr: [],
  },
  zh: {
    custom: {},
    replacemenKeyArr: [],
  },
}

const commonMessageRequests = new Map<LocalePath, Promise<unknown>>();
let customMessageRequest: Promise<void> | undefined;

const fetchLocaleJson = async (path: string) => {
  const response = await fetch(withBasePath(path), { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`Failed to load locale resource ${path}: ${response.status}`);
  }

  return response.json();
};

const loadCachedRequest = async <T,>(
  cache: Map<LocalePath, Promise<T>>,
  locale: LocalePath,
  load: () => Promise<T>
): Promise<T> => {
  const cachedRequest = cache.get(locale);
  if (cachedRequest) {
    return cachedRequest;
  }

  const request = load();
  cache.set(locale, request);

  try {
    return await request;
  } catch (error) {
    if (cache.get(locale) === request) {
      cache.delete(locale);
    }
    throw error;
  }
};

const loadCustomMessages = () => {
  if (!customMessageRequest) {
    customMessageRequest = Promise.all(
      (["zh", "en"] as const).map(async (locale) => {
        const custom = await fetchLocaleJson(
          `/locales/${locale}/custom.json`
        );
        return [locale, custom] as const;
      })
    )
      .then((entries) => {
        entries.forEach(([locale, custom]) => {
          if (resourcesCustom[locale]) {
            resourcesCustom[locale].custom = custom;
            resourcesCustom[locale].replacemenKeyArr = Object.entries(custom).map(
              ([pattern, str]) => ({ pattern, str: String(str) })
            );
          }
        });
      })
      .catch((error) => {
        customMessageRequest = undefined;
        throw error;
      });
  }

  return customMessageRequest;
};

export const loadLocaleMessages = async (locale: string) => {
  const localePath: LocalePath = locale.toLowerCase().startsWith("zh")
    ? "zh"
    : "en";

  try {
    const [common] = await Promise.all([
      loadCachedRequest(commonMessageRequests, localePath, () =>
        fetchLocaleJson(`/locales/${localePath}/common.json`)
      ),
      loadCustomMessages(),
    ]);

    resources[localePath].common = common;

    return { resourcesCustom, resources };
  } catch (error) {
    log.error(`Failed to load locale ${locale}`, error);
  }
  return { resourcesCustom, resources };
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
