// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Page } from "playwright/test";
import { deflateSync } from "node:zlib";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { appPath } from "../../infra/automation/d4/runner/runtime-config";

function logoPng(width: number, height: number, color: number[]): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const pixels = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++)
      pixels.set(color, y * (width * 3 + 1) + 1 + x * 3);
  }
  const chunk = (type: string, data: Buffer) => {
    const content = Buffer.concat([Buffer.from(type), data]);
    let crc = 0xffffffff;
    for (const byte of content) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++)
        crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
    return Buffer.concat([length, content, checksum]);
  };
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(pixels)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
const png = logoPng(320, 64, [0, 103, 209]);
const homePng = logoPng(320, 80, [145, 70, 210]);

async function recordTitles(page: Page) {
  await page.addInitScript(() => {
    const state = window as Window & { brandingTitles: string[] };
    state.brandingTitles = [document.title];
    new MutationObserver(() => {
      if (state.brandingTitles.at(-1) !== document.title)
        state.brandingTitles.push(document.title);
    }).observe(document, {
      subtree: true,
      childList: true,
      characterData: true,
    });
  });
}

async function expectNoDefaultTitle(page: Page) {
  const titles = await page.evaluate(
    () => (window as Window & { brandingTitles: string[] }).brandingTitles,
  );
  expect(titles).not.toContain("Nexent");
}

journey("SYSTEM-BRANDING-D4-001", async (context) => {
  const { page, contract } = context;
  const request = page.context().request;
  let originalZh: Record<string, string>;
  let originalEn: Record<string, string>;
  let systemLogo: Buffer;
  let homepageLogo: Buffer | undefined;
  let savedHomeLogo = "";
  let originalRestored = false;
  let titledBrandWidth = 0;
  const title = (locale: "zh" | "en", name: string) =>
    page.getByRole("textbox", {
      name: locale === "zh" ? name : `${name}-English`,
      exact: true,
    });
  const open = async () => {
    await page.goto(appPath("/resource-manage"));
    await page.getByRole("button", { name: "系统配置", exact: true }).click();
    await expect(title("zh", "导航栏标题（页面左上角）")).toBeVisible();
  };
  const save = async () => {
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes("/api/config/project-config"),
    );
    await page.getByRole("button", { name: "保存", exact: true }).click();
    expect((await response).status()).toBe(200);
    await page.waitForLoadState("domcontentloaded");
    await page.reload();
  };
  const icon = () => page.locator('head link[rel="icon"]').first();
  const expectTransparentIcons = async () => {
    const icons = page.locator('head link[rel*="icon"]');
    await expect(icons).toHaveCount(3);
    for (const link of await icons.all())
      await expect(link).toHaveAttribute("href", /^data:image\/svg\+xml,/);
  };
  const rail = () => page.locator("[data-sidebar-expanded]");
  const brand = () => rail().locator("a").first();
  const expectSystemTab = async () => {
    await expect(page).toHaveTitle("Branding system");
    await expect(icon()).toHaveAttribute("href", /\/modelengine-logo\.png$/);
  };
  const restore = async () => {
    if (originalRestored) return;
    const configZh = JSON.stringify({
      ...originalZh,
      homeTitle: originalZh.homeTitle ?? originalZh.tabTitle ?? "",
    });
    const configEn = JSON.stringify({
      ...originalEn,
      homeTitle: originalEn.homeTitle ?? originalEn.tabTitle ?? "",
    });
    const response = await request.post("/api/config/project-config", {
      multipart: {
        configZh,
        configEn,
        logo2: {
          name: "system.png",
          mimeType: "image/png",
          buffer: systemLogo,
        },
        removeHomeLogo: "true",
      },
    });
    expect(response.status()).toBe(200);
    if (homepageLogo) {
      const upload = await request.post("/api/config/project-config", {
        multipart: {
          configZh,
          configEn,
          homeLogo: {
            name: "home.png",
            mimeType: "image/png",
            buffer: homepageLogo,
          },
        },
      });
      expect(upload.status()).toBe(200);
    }
    const restoredConfig = await (
      await request.get("/locales/zh/custom.json")
    ).json();
    expect(restoredConfig.productName).toBe(originalZh.productName);
    expect(restoredConfig.homeTitle).toBe(
      originalZh.homeTitle ?? originalZh.tabTitle ?? "",
    );
    expect(await (await request.get("/modelengine-logo.png")).body()).toEqual(
      systemLogo,
    );
    if (homepageLogo)
      expect(
        await (await request.get(`/${restoredConfig.homeLogo}`)).body(),
      ).toEqual(homepageLogo);
    originalRestored = true;
  };
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "super_admin");
        return "isolated SUPER_ADMIN session";
      },
      async () => {
        originalZh = await (
          await request.get("/locales/zh/custom.json")
        ).json();
        originalEn = await (
          await request.get("/locales/en/custom.json")
        ).json();
        systemLogo = await (await request.get("/modelengine-logo.png")).body();
        const originalLogo = originalZh.homeLogo ?? originalZh.tabLogo ?? "";
        if (
          /^(home-logo|browser-tab-logo)\.(png|jpg)(\?v=[a-f0-9]+)?$/.test(
            originalLogo,
          )
        ) {
          homepageLogo = await (await request.get(`/${originalLogo}`)).body();
        }
        contract.deferCleanup(restore);
        return "original locale and logo values retained for restoration";
      },
    ],
    steps: [
      async () => {
        await open();
        await title("zh", "应用名称（网页标签页标题）").fill("Branding system");
        await title("en", "应用名称（网页标签页标题）").fill("Branding system");
        await title("zh", "导航栏标题（页面左上角）").fill("");
        await title("en", "导航栏标题（页面左上角）").fill("");
        const reset = page.getByRole("button", {
          name: "使用应用 Logo",
          exact: true,
        });
        if (await reset.isEnabled()) await reset.click();
        await page.locator('input[type="file"]').nth(0).setInputFiles({
          name: "system.png",
          mimeType: "image/png",
          buffer: png,
        });
        await save();
        await expectSystemTab();
        await recordTitles(page);
        let release!: () => void;
        let requested!: () => void;
        const blocked = new Promise<void>((resolve) => {
          release = resolve;
        });
        const seen = new Promise<void>((resolve) => {
          requested = resolve;
        });
        const customJson = /\/locales\/(zh|en)\/custom\.json(?:\?|$)/;
        const systemImage = /\/modelengine-logo\.png(?:\?|$)/;
        let imageRequested!: () => void;
        const imageSeen = new Promise<void>((resolve) => {
          imageRequested = resolve;
        });
        await page.route(customJson, async (route) => {
          requested();
          await blocked;
          await route.continue();
        });
        await page.route(systemImage, async (route) => {
          imageRequested();
          await blocked;
          await route.continue();
        });
        try {
          const response = await page.reload({ waitUntil: "domcontentloaded" });
          await Promise.all([seen, imageSeen]);
          const html = await response!.text();
          expect(html).not.toMatch(/<title[^>]*>Nexent<\/title>/);
          expect(html).toMatch(
            /<link\b[^>]*rel="icon"[^>]*href="data:image\/svg\+xml,/,
          );
          await expect(page).toHaveTitle("");
          await expectTransparentIcons();
        } finally {
          release();
          await page.unroute(customJson);
          await page.unroute(systemImage);
        }
        await expectSystemTab();
        let imageFailed!: () => void;
        const failed = new Promise<void>((resolve) => {
          imageFailed = resolve;
        });
        await page.route(systemImage, async (route) => {
          await route.abort("failed");
          imageFailed();
        });
        try {
          await page.reload({ waitUntil: "domcontentloaded" });
          await failed;
          await expect(
            page.getByRole("button", { name: "系统配置", exact: true }),
          ).toBeVisible();
          await expectTransparentIcons();
        } finally {
          await page.unroute(systemImage);
        }
        await page.reload();
        await expectSystemTab();
        await expectNoDefaultTitle(page);
        await rail().hover();
        await expect(brand()).toHaveText("");
        await expect(brand().getByRole("img")).toHaveAttribute(
          "src",
          /\/modelengine-logo\.png$/,
        );
        return "empty homepage title remains blank and its logo falls back; browser uses system branding";
      },
      async () => {
        await open();
        await title("zh", "导航栏标题（页面左上角）").fill("独立首页标题");
        await title("en", "导航栏标题（页面左上角）").fill(
          "Independent homepage",
        );
        await page.locator('input[type="file"]').nth(1).setInputFiles({
          name: "home.png",
          mimeType: "image/png",
          buffer: homePng,
        });
        await save();
        await expectSystemTab();
        const loginContext = await page
          .context()
          .browser()!
          .newContext({ locale: "zh-CN" });
        try {
          const signedInPage = await loginContext.newPage();
          await recordTitles(signedInPage);
          await loginCurrent(signedInPage, "tenant_a_admin");
          await expect(signedInPage).toHaveTitle("Branding system");
          const sidebar = signedInPage.locator("[data-sidebar-expanded]");
          await sidebar
            .getByRole("button", { name: "工作台", exact: true })
            .click();
          await expect(signedInPage).toHaveURL(/\/zh\/workbench(?:\?|$)/);
          await expect(signedInPage).toHaveTitle("Branding system");
          await sidebar
            .getByRole("button", { name: "智能体配置", exact: true })
            .click();
          await expect(signedInPage).toHaveURL(/\/zh\/agents(?:\?|$)/);
          await expect(signedInPage).toHaveTitle("Branding system");
          await expectNoDefaultTitle(signedInPage);
        } finally {
          await loginContext.close();
        }
        await rail().hover();
        await expect(rail()).toHaveCSS("width", "240px");
        await expect(brand()).toHaveText("独立首页标题");
        const logo = brand().getByRole("img");
        savedHomeLogo = (await logo.getAttribute("src"))!;
        expect(savedHomeLogo).toMatch(/home-logo\.png\?v=[a-f0-9]+$/);
        titledBrandWidth = await brand().evaluate((element) => {
          const style = getComputedStyle(element);
          return (
            element.getBoundingClientRect().width -
            parseFloat(style.paddingLeft) -
            parseFloat(style.paddingRight)
          );
        });
        await page.goto("/en/workbench");
        await expectSystemTab();
        await rail().hover();
        await expect(brand()).toHaveText("Independent homepage");
        await expect(brand().getByRole("img")).toHaveAttribute(
          "src",
          savedHomeLogo,
        );
        expect(
          await (await request.get("/modelengine-logo.png")).body(),
        ).toEqual(png);
        return "homepage branding follows locale/routes and never changes browser system branding";
      },
      async () => {
        await open();
        await title("zh", "导航栏标题（页面左上角）").fill("");
        await save();
        await expectSystemTab();
        await rail().hover();
        await expect(rail()).toHaveCSS("width", "240px");
        await expect(brand()).toHaveText("");
        const logo = brand().getByRole("img");
        await expect(logo).toHaveAttribute("src", savedHomeLogo);
        await expect(logo).toHaveCSS("object-fit", "contain");
        const width = (await logo.boundingBox())!.width;
        expect(width).toBe(160);
        expect((await logo.boundingBox())!.height).toBe(40);
        expect(width).toBeLessThan(titledBrandWidth);
        await page.mouse.move(500, 100);
        await expect(rail()).toHaveAttribute("data-sidebar-expanded", "false");
        await expect(rail()).toHaveCSS("width", "64px");
        await expect(brand()).toHaveCSS("overflow-x", "hidden");
        const collapsedLogo = (await logo.boundingBox())!;
        const collapsedBrand = (await brand().boundingBox())!;
        expect(Math.abs(collapsedLogo.width - width)).toBeLessThanOrEqual(1);
        expect(collapsedBrand.width).toBeLessThanOrEqual(48);
        expect(
          Math.abs(collapsedLogo.x - collapsedBrand.x - 2),
        ).toBeLessThanOrEqual(1);
        expect(collapsedLogo.x + collapsedLogo.width).toBeGreaterThan(
          collapsedBrand.x + collapsedBrand.width,
        );
        await rail().hover();
        await expect(rail()).toHaveCSS("width", "240px");
        expect(
          Math.abs((await logo.boundingBox())!.width - width),
        ).toBeLessThanOrEqual(1);
        return "blank-title image keeps its expanded size while the collapsed brand viewport clips its right side";
      },
      async () => {
        await open();
        await title("zh", "导航栏标题（页面左上角）").fill("");
        await title("en", "导航栏标题（页面左上角）").fill("");
        await page
          .getByRole("button", { name: "使用应用 Logo", exact: true })
          .click();
        await save();
        await expectSystemTab();
        await rail().hover();
        await expect(brand()).toHaveText("");
        await expect(brand().getByRole("img")).toHaveAttribute(
          "src",
          /\/modelengine-logo\.png$/,
        );
        await restore();
        return "cleared homepage logo falls back without adding a title; original branding is restored";
      },
    ],
    assertions: [
      async () => {
        expect(savedHomeLogo).toContain("home-logo.png?v=");
        return "homepage persistence, locale navigation and browser isolation proved in steps 1/2/4";
      },
      async () => {
        await restore();
        return "blank-title/logo fallback and restoration assertions completed";
      },
      async () => {
        expect(titledBrandWidth).toBeGreaterThan(48);
        return "smaller proportional image, unchanged dimensions and left-aligned clipping verified in step 3";
      },
      async () => {
        await expectNoDefaultTitle(page);
        return "blank delayed-load title and real login/sidebar title history verified in steps 1/2";
      },
      async () => {
        return "transparent SSR/loading/error icon states and successful system-logo recovery verified in step 1";
      },
    ],
  });
});
