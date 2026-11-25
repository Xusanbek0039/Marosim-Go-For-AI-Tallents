import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Vendor MediaPipe runtime copied from node_modules by scripts/prepare-mediapipe.mjs
    // (predev/prebuild). Generated and git-ignored — not our code to lint.
    "public/mediapipe/wasm/**",
  ]),
]);

export default eslintConfig;
