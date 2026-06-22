/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**' },
    ],
  },
  async rewrites() {
    if (process.env.NODE_ENV === 'development') {
      return [{
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      }]
    }
    return []
  },
}
module.exports = nextConfig
