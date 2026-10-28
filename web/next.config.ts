import type { NextConfig } from 'next'

// The Python analysis service.  Locally it is uvicorn on 8000; in the cloud set
// API_BASE to the service URL and the browser keeps talking to the Next origin,
// so there is no CORS and no second host to whitelist.
const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000'

// Standalone output is what the Docker image ships; leaving it off locally keeps
// plain `next start` working (Next warns when the two are mixed).
const standalone = process.env.NEXT_OUTPUT === 'standalone'

const nextConfig: NextConfig = {
  // Pin the tracing root to web/. Without this, a stray package-lock.json in a parent
  // folder makes Next guess the repo root and warn on every build.
  outputFileTracingRoot: process.cwd(),
  ...(standalone ? { output: 'standalone' as const } : {}),
  async rewrites() {
    return [{ source: '/api/:path*', destination: API_BASE + '/api/:path*' }]
  },
}

export default nextConfig
