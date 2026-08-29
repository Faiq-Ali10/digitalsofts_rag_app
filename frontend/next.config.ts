import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ['204.216.106.54'],
  env: {
    NEXT_PUBLIC_API_URL: 'http://204.216.106.54:8000',
    NEXT_PUBLIC_BACKEND_URL: 'http://204.216.106.54:8000'
  }
  // ... any other existing settings ...
};

export default nextConfig;