/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**' },
    ],
  },
  async rewrites() {
    // API_URL is the internal Railway URL (available at runtime, not bake-time).
    // NEXT_PUBLIC_API_URL and hardcoded fallback cover cases where API_URL isn't set.
    const apiBase =
      process.env.API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      (process.env.NODE_ENV === 'development'
        ? 'http://localhost:8000'
        : 'https://luminous-essence-production-ad00.up.railway.app')
    return [{
      source: '/api/:path*',
      destination: `${apiBase}/api/:path*`,
    }]
  },
}
module.exports = nextConfig
