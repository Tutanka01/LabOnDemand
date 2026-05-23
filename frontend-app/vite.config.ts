import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

export default defineConfig({
  appType: "mpa",
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      input: {
        register: resolve(__dirname, "register.html"),
        login: resolve(__dirname, "login.html"),
        dashboard: resolve(__dirname, "index.html"),
        teacher: resolve(__dirname, "teacher.html"),
        admin: resolve(__dirname, "admin.html"),
        adminStats: resolve(__dirname, "admin-stats.html"),
        accessDenied: resolve(__dirname, "access-denied.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
