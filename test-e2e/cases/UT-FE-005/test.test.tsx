// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { useLanguageSwitch } from '@/lib/language';
import i18n, { loadLocaleMessages } from '@/app/[locale]/i18n';

const fixture = vi.hoisted(() => ({ pathname: '/portal/zh/agents/7', language: 'zh' }));
vi.mock('@/base-path.mjs', () => ({ BASE_PATH: '/portal' }));
vi.mock('next/navigation', () => ({ usePathname: () => fixture.pathname }));
vi.mock('react-i18next', async (original) => ({
  ...await original<typeof import('react-i18next')>(),
  useTranslation: () => ({ i18n: { language: fixture.language } }),
}));
function SwitchLanguage() {
  const state = useLanguageSwitch();
  return <button onClick={() => state.handleLanguageChange(state.getOppositeLanguage().lang)}>
    {state.currentLanguage}:{state.getOppositeLanguage().label}
  </button>;
}
beforeEach(() => { fixture.pathname = '/portal/zh/agents/7'; fixture.language = 'zh'; });
afterEach(() => {
  vi.unstubAllGlobals(); vi.restoreAllMocks();
  document.cookie = 'NEXT_LOCALE=; path=/; max-age=0';
});
describe('UT-FE-005 locale behavior', () => {
  it.each([
    ['zh', '/portal/zh/agents/7', '/portal/en/agents/7'],
    ['en', '/portal/en/newchat', '/portal/zh/newchat'],
    ['zh', '/portal/agents/7', '/portal/en/agents/7'],
    ['en', '/portal', '/portal/zh'],
  ])('switches %s and preserves route %s', (language, pathname, expected) => {
    fixture.language = language; fixture.pathname = pathname;
    const navigation = { href: '' };
    const originalWindow = window;
    // Observe navigation without replacing the route computation.
    vi.stubGlobal('window', new Proxy(originalWindow, {
      get(target, key) { return key === 'location' ? navigation : Reflect.get(target, key, target); },
    }));
    render(<SwitchLanguage />);
    fireEvent.click(screen.getByRole('button'));
    expect(navigation.href).toBe(expected);
    expect(document.cookie).toContain('NEXT_LOCALE=' + (language === 'zh' ? 'en' : 'zh'));
  });
  it('loads unknown locale from English and preserves translation fallback', async () => {
    // i18n.tsx memoises requests in module singletons; reload for a fresh cache.
    vi.resetModules();
    const freshI18n = await import('@/app/[locale]/i18n');
    const request = vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () =>
        url.endsWith('common.json') ? { 'test.fallback': 'English fallback' } : {},
    }));
    vi.stubGlobal('fetch', request);
    const loaded = await freshI18n.loadLocaleMessages('unsupported');
    expect(request.mock.calls.map(([url]) => url)).toEqual([
      '/portal/locales/en/common.json', '/portal/locales/zh/custom.json', '/portal/locales/en/custom.json',
    ]);
    // `common` lives on `resources`; `resourcesCustom` only holds the overlay.
    const freshDefault = freshI18n.default;
    freshDefault.addResourceBundle('en', 'common', loaded.resources.en.common ?? {}, true, true);
    await freshDefault.changeLanguage('zh');
    expect(freshDefault.t('test.fallback')).toBe('English fallback');
    expect(freshDefault.t('test.notDefined', { defaultValue: 'Safe default' })).toBe('Safe default');
  });
  it('locale load failure preserves already-loaded messages', async () => {
    vi.resetModules();
    const freshI18n = await import('@/app/[locale]/i18n');
    freshI18n.default.addResourceBundle('en', 'common', { 'test.fallback': 'English fallback' }, true, true);
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline fixture')));
    await freshI18n.loadLocaleMessages('en');
    // A failed load must not clear what i18next already holds.
    expect(freshI18n.default.hasResourceBundle('en', 'common')).toBe(true);
    await freshI18n.default.changeLanguage('en');
    expect(freshI18n.default.t('test.fallback')).toBe('English fallback');
  });
});
