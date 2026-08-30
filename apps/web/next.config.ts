import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Three.js e seus wrappers React precisam ser transpilados pelo Next.js
  // para funcionar corretamente com o App Router (ESM + SSR desabilitado)
  transpilePackages: ["three", "@react-three/fiber", "@react-three/drei"],

  images: {
    formats: ["image/avif", "image/webp"],
  },

  // Headers de segurança básicos
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-XSS-Protection", value: "1; mode=block" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
