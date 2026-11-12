import { readFileSync } from "node:fs";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

const pyproject = readFileSync(new URL("../pyproject.toml", import.meta.url), "utf-8");
const version = /^version = "([^"]+)"/m.exec(pyproject)?.[1] ?? "0+unknown";
const pi = process.env.WOW_PI ?? "https://localhost:8443";

export default defineConfig({
  plugins: [svelte()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  build: {
    outDir: "../src/wow/web/static",
    emptyOutDir: true,
    assetsDir: "assets",
    target: "safari16",
  },
  server: {
    proxy: { "/ws": { target: pi, ws: true, secure: false } },
  },
  resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});
