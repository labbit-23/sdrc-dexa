/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow images from self-hosted Supabase storage
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: '192.168.1.50',
        port: '8000',
        pathname: '/storage/v1/object/public/**',
      },
    ],
  },
}

module.exports = nextConfig
