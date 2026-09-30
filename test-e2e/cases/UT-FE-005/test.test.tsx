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
    const request = vi.fn(async (url: string) => ({ json: async () =>
      url.endsWith('common.json') ? { 'test.fallback': 'English fallback' } : {} }));
    vi.stubGlobal('fetch', request);
    const loaded = await loadLocaleMessages('unsupported');
    expect(request.mock.calls.map(([url]) => url)).toEqual([
      '/portal/locales/en/common.json', '/portal/locales/zh/custom.json', '/portal/locales/en/custom.json',
    ]);
    i18n.addResourceBundle('en', 'common', loaded.resources.en.common, true, true);
    await i18n.changeLanguage('zh');
    expect(i18n.t('test.fallback')).toBe('English fallback');
    expect(i18n.t('test.notDefined', { defaultValue: 'Safe default' })).toBe('Safe default');
  });
  it('locale load failure preserves already-loaded messages', async () => {
    i18n.addResourceBundle('en', 'common', { 'test.fallback': 'English fallback' }, true, true);
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline fixture')));
    const result = await loadLocaleMessages('en');
    expect(result.resources.en.common).toHaveProperty('test.fallback', 'English fallback');
  });
});
