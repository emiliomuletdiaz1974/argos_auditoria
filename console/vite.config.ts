/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The console is served by the v1 API from `/` (ADR-0013): one origin, no CDN, nothing fetched
// at run time from outside the appliance (P-03).
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8009" } },
  test: {
    environment: "jsdom",
    // jsdom only offers localStorage and sessionStorage to a page with an origin.
    environmentOptions: { jsdom: { url: "https://argos.appliance.example/" } },
    // Node 26 ships its own Web Storage global, which would shadow the one of jsdom.
    pool: "forks",
    poolOptions: { forks: { execArgv: ["--no-experimental-webstorage"] } },
    globals: true,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
