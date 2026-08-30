import js from "@eslint/js";
import nextPlugin from "eslint-config-next";
import prettierConfig from "eslint-config-prettier";

/** @type {import('eslint').Linter.Config[]} */
const config = [
  js.configs.recommended,
  ...nextPlugin,
  prettierConfig,
  {
    rules: {
      // Proibir `any` explícito — usar tipos ou `unknown` com narrowing
      "@typescript-eslint/no-explicit-any": "error",
      // Exigir tipos de retorno em funções exportadas
      "@typescript-eslint/explicit-module-boundary-types": "off",
      // Evitar variáveis não utilizadas
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Preferir const
      "prefer-const": "error",
      // Sem console.log em produção (usar logger estruturado no futuro)
      "no-console": ["warn", { allow: ["warn", "error"] }],
    },
  },
  {
    ignores: [".next/**", "node_modules/**", "supabase/**"],
  },
];

export default config;
