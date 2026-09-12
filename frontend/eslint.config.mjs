import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTypescript,
  { ignores: [".next/**", ".test-dist/**", "test-results/**", "playwright-report/**", "next-env.d.ts"] },
];
export default config;
