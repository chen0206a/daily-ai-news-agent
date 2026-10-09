import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.BUILD_STANDALONE === "true" ? "standalone" : undefined,
  async rewrites() {
    return [{source: "/api/:path*", destination: `${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/api/:path*`}];
  },
  async headers() {
    return [{source: "/:path*", headers: [
      {key: "X-Content-Type-Options", value: "nosniff"},
      {key: "X-Frame-Options", value: "DENY"},
      {key: "Referrer-Policy", value: "no-referrer"},
      {key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()"}
    ]}];
  }
};
export default nextConfig;
