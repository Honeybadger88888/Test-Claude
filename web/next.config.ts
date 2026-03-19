import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: [
    "p-3000-pod-26mi6mnvxreafggei6gmahtxoe-cabb8de6be85f2622d5c-us3p.agent.cvm.dev",
    "https://p-3000-pod-26mi6mnvxreafggei6gmahtxoe-cabb8de6be85f2622d5c-us3p.agent.cvm.dev",
  ],
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: "http://127.0.0.1:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
