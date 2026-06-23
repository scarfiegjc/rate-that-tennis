/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**' },
    ],
  },
  async rewrites() {
    // In development, proxy to local FastAPI.
    // In production, always proxy to luminous-essence (the FastAPI service).
    // NOTE: API_URL and NEXT_PUBLIC_API_URL on this service were set to the old
    // nginx service — ignore them and use the correct URL directly.
    const apiBase =
      process.env.NODE_ENV === 'development'
        ? 'http://localhost:8000'
        : 'https://luminous-essence-production-ad00.up.railway.app'
    return [{
      source: '/api/:path*',
      destination: `${apiBase}/api/:path*`,
    }]
  },
}
module.exports = nextConfig
