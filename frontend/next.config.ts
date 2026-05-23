import type { NextConfig } from "next";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND}/:path*`,
      },
    ];
  },
};

export default nextConfig;
