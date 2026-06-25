/** @type {import('next').NextConfig} */
const nextConfig = {
  // Frontend talks to the FastAPI backend + Supabase; skip lint during build
  // so CI never blocks on it.
  eslint: { ignoreDuringBuilds: true },
  // The WebSocket hook holds one long-lived connection; StrictMode's dev
  // double-mount would open/abort a second socket and thrash the singleton
  // replay engine. One stable connection is what we want.
  reactStrictMode: false,
};

export default nextConfig;
