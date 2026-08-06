import { fileURLToPath } from 'node:url';

const legacyHslColorMixPlugin = fileURLToPath(
  new URL('./postcss-legacy-hsl-color-mix.cjs', import.meta.url),
);

/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    // postcss-nested runs first so Sass-style `& selector` syntax (used by
    // react-shiki's CSS and other third-party stylesheets) is expanded before
    // Tailwind v4's PostCSS plugin sees the input. See:
    // https://github.com/tailwindlabs/tailwindcss/issues/14844
    'postcss-nested': {},
    '@tailwindcss/postcss': {},
    // Tailwind v4's default palette uses oklch(), which Chrome < 111 cannot
    // resolve when the values are consumed through CSS custom properties.
    '@csstools/postcss-oklab-function': {
      preserve: false,
    },
    // Tailwind cannot precompute opacity modifiers for theme colors that are
    // backed by HSL custom properties, so add an older-syntax fallback.
    [legacyHslColorMixPlugin]: {},
  },
};

export default config;
