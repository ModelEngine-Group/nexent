import { NextRequest, NextResponse } from "next/server";

import { BASE_PATH } from "./base-path.mjs";

const PUBLIC_FILE = /\.(.*)$/;
const locales = ["zh", "en"];
const defaultLocale = "zh";

function withoutBasePath(pathname: string): string {
  if (!BASE_PATH || (pathname !== BASE_PATH && !pathname.startsWith(`${BASE_PATH}/`))) {
    return pathname;
  }

  return pathname.slice(BASE_PATH.length) || "/";
}

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const appPathname = withoutBasePath(pathname);

  // Ignore static resources and API routes.
  if (
    appPathname.startsWith("/_next") ||
    appPathname.startsWith("/api") ||
    PUBLIC_FILE.test(appPathname)
  ) {
    return;
  }

  const hasLocale = locales.some(
    (locale) => appPathname === `/${locale}` || appPathname.startsWith(`/${locale}/`)
  );

  if (!hasLocale) {
    let detectedLocale = defaultLocale;
    const cookieLocale = req.cookies.get("NEXT_LOCALE")?.value;

    if (cookieLocale && locales.includes(cookieLocale)) {
      detectedLocale = cookieLocale;
    } else {
      const acceptLang = req.headers.get("accept-language");
      if (acceptLang) {
        const preferred = acceptLang.split(",")[0].toLowerCase();
        if (preferred.startsWith("en")) detectedLocale = "en";
        else if (preferred.startsWith("zh")) detectedLocale = "zh";
      }
    }

    const url = req.nextUrl.clone();
    const redirectPrefix = req.nextUrl.basePath ? "" : BASE_PATH;
    url.pathname = `${redirectPrefix}/${detectedLocale}${appPathname}`;
    return NextResponse.redirect(url);
  }
}