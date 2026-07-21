/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    // postcss-nested runs first so Sass-style `& selector` syntax (used by
    // react-shiki's CSS and other third-party stylesheets) is expanded before
    // Tailwind v4's PostCSS plugin sees the input. See:
    // https://github.com/tailwindlabs/tailwindcss/issues/14844
    'postcss-nested': {},
    '@tailwindcss/postcss': {},
  },
};

export default config;