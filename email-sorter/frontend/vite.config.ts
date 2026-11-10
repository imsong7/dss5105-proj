import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Flask serves the production build from static/app/ at /dashboard-v2, so
// assets load from /static/app/. In dev, Vite proxies the Flask routes so the
// session cookie and /api calls stay same-origin.
export default defineConfig(({ mode }) => {
  const flask = loadEnv(mode, ".", "").FLASK_URL ?? "http://127.0.0.1:5001";

  return {
  base: "/static/app/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../static/app",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": flask,
      "/login": flask,
      "/logout": flask,
      "/register": flask,
      "/feed": flask,
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
};
});
