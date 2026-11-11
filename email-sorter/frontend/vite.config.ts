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
    // changeOrigin: false keeps the browser's Host (127.0.0.1:5173), so it
    // matches the Origin and Flask's same-origin check on writes passes.
    // (The string shorthand rewrites Host to Flask's port and gets a 403.)
    proxy: Object.fromEntries(
      ["/api", "/login", "/logout", "/register", "/feed"].map((path) => [
        path,
        { target: flask, changeOrigin: false },
      ]),
    ),
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
};
});
