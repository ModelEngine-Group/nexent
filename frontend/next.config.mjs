import { BASE_PATH } from "./base-path.mjs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let userConfig = undefined
try {
  userConfig = await import('./v0-user-next.config')
} catch (e) {
  // ignore error
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  basePath: BASE_PATH,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  experimental: {
    webpackBuildWorker: true,
    parallelServerBuildTraces: true,
    parallelServerCompiles: true,
  },
  compress: true,
  // Fix workspace root detection for multiple lockfiles
  outputFileTracingRoot: process.cwd(),
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    // Resolve AG-UI packages from .pnpm store using absolute paths,
    // because pnpm's isolated node_modules doesn't hoist them to the top level.
    const pnpmRoot = `${__dirname}/node_modules/.pnpm`;
    config.resolve.alias = {
      ...config.resolve.alias,
      "@ag-ui/client": `${pnpmRoot}/@ag-ui+client@0.0.59/node_modules/@ag-ui/client`,
      "@ag-ui/core": `${pnpmRoot}/@ag-ui+client@0.0.59/node_modules/@ag-ui/core`,
    };
    return config;
  },
}

mergeConfig(nextConfig, userConfig)

function mergeConfig(nextConfig, userConfig) {
  if (!userConfig) {
    return
  }

  for (const key in userConfig) {
    if (
      typeof nextConfig[key] === 'object' &&
      !Array.isArray(nextConfig[key])
    ) {
      nextConfig[key] = {
        ...nextConfig[key],
        ...userConfig[key],
      }
    } else {
      nextConfig[key] = userConfig[key]
    }
  }
}

export default nextConfig
