import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Strict mode for React — detecta efeitos colaterais inesperados
  reactStrictMode: true,

  // Permite importar SVGs e outros assets estáticos
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
