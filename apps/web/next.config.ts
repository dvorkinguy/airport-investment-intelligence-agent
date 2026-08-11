import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // public/3d/index.html has no directory-index resolution on its own -
  // Next only serves it at the literal /3d/index.html path. This rewrite
  // (not a redirect) keeps the clean /3d URL while serving that same file,
  // and runs independently of middleware.ts's matcher/auth gate.
  async rewrites() {
    return [{ source: "/3d", destination: "/3d/index.html" }];
  },
};

export default nextConfig;
