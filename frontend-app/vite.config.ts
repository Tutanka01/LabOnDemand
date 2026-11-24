import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Framework code changes far less often than the app: keeping it in its own
// fingerprinted chunk lets browsers reuse it across deployments.
const VENDOR = /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@tanstack[\\/](react-query|query-core))[\\/]/;

export default defineConfig({
  appType: "spa",
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (VENDOR.test(id)) return "vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", ws: true },
    },
  },
});
