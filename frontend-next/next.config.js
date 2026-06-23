/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**' },
    ],
  },
  async rewrites() {
    // In dev, proxy to local FastAPI. In production, proxy to Railway internal API_URL.
    const apiBase =
      process.env.NODE_ENV === 'development'
        ? 'http://localhost:8000'
        : (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')
    return [{
      source: '/api/:path*',
      destination: `${apiBase}/api/:path*`,
    }]
  },
}
module.exports = nextConfig
