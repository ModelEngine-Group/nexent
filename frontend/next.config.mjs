let userConfig = undefined
try {
  userConfig = await import('./v0-user-next.config')
} catch (e) {
  // ignore error
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
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
    // Transform barrel imports (antd, icon libs, radix) into per-file imports so
    // webpack does not pull the entire barrel into the dev module graph on every
    // route compile. Cuts first-compile time for routes that use these libs.
    optimizePackageImports: [
      "antd",
      "@ant-design/icons",
      "lucide-react",
      "@radix-ui/react-scroll-area",
      "@radix-ui/react-tabs",
    ],
  },
  compress: true,
  // Fix workspace root detection for multiple lockfiles
  outputFileTracingRoot: process.cwd(),
  webpack: (config) => {
    config.resolve.alias.canvas = false;
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
