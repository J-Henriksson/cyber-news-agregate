import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Relative, so the same build is served at / here and under /<repository>/ on GitHub Pages.
  base: "./",
  plugins: [react()],
  server: {
    port: 5740,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8740" },
  },
});
