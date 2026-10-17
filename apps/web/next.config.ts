import type { NextConfig } from "next";
import path from "node:path";

const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  output: "standalone",
  outputFileTracingRoot: path.resolve(import.meta.dirname, "../.."),
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      { key: "Content-Security-Policy", value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'" },
    ] }];
  },
  async rewrites() {
    const backend = process.env.API_ORIGIN || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default config;

