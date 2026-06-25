/** @type {import('next').NextConfig} */
const nextConfig = {
  // Frontend is pure client/SSR talking to the FastAPI backend + Supabase;
  // skip lint during build so CI/Vercel never blocks on it.
  eslint: { ignoreDuringBuilds: true },
  // The WebSocket hook holds one long-lived connection; StrictMode's dev
  // double-mount would open/abort a second socket and thrash the singleton
  // replay engine. One stable connection is what we want.
  reactStrictMode: false,
  // Self-contained server bundle for a tiny Docker image (ignored by Vercel).
  output: "standalone",
};

export default nextConfig;
