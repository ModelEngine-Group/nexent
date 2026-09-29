import { NextRequest, NextResponse } from "next/server";

/**
 * Redirect locale-less page paths into the [locale] segment.
 *
 * The sidebar and several legacy entries push bare paths such as
 * "/knowledges". Without a locale prefix the [locale] route receives a
 * garbage locale and the page crashes inside the i18n initializer
 * (I18nProviderWrapper reads resourcesCustom[locale]). Redirecting here
 * sends every bare path to its localized counterpart based on the
 * NEXT_LOCALE cookie instead.
 */

const LOCALES = new Set(["zh", "en"]);

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const firstSegment = pathname.split("/")[1];
  if (LOCALES.has(firstSegment)) {
    return NextResponse.next();
  }

  const locale =
    request.cookies.get("NEXT_LOCALE")?.value === "en" ? "en" : "zh";
  const url = request.nextUrl.clone();
  url.pathname = pathname === "/" ? `/${locale}` : `/${locale}${pathname}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Skip the API, Next.js internals, public assets (the /locales JSON files
  // included) and anything with a file extension.
  matcher: ["/((?!api|_next|locales|.*\\..*).*)"],
};
