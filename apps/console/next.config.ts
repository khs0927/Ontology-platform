import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    // Document uploads go through a server action; the API enforces its own limit
    // (SION_UPLOAD_MAX_BYTES, 25 MiB by default), so allow a little more than that here.
    serverActions: { bodySizeLimit: "26mb" },
    proxyClientMaxBodySize: "26mb",
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
