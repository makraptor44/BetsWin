import path from "node:path";

import type { NextConfig } from "next";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/**
 * Static-demo build (GitHub Pages).
 *
 * There is no Python process behind the deployed demo, so the app is exported
 * as plain files and the API client reads JSON fixtures instead. A normal build
 * leaves this off and proxies to the live backend.
 */
const STATIC_DEMO = process.env.NEXT_PUBLIC_STATIC_DEMO === "true";
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Pin the workspace root to this folder. Turbopack otherwise walks up looking
  // for a lockfile and can land on one in the user's home directory, which it
  // then refuses to use -- harmless, but it prints a warning on every start.
  turbopack: { root: path.resolve(process.cwd()) },

  ...(STATIC_DEMO
    ? {
        output: "export" as const,
        basePath: BASE_PATH,
        trailingSlash: true,
        images: { unoptimized: true },
      }
    : {
        // Proxy the API in development so the browser talks to one origin and
        // no CORS preflight is needed. Rewrites cannot exist alongside
        // `output: "export"`, hence the split.
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
        },
      }),
};

export default nextConfig;
