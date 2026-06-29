import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API client calls the backend at `/api/...`. In dev, Vite proxies
// `/api` → http://localhost:8000 and strips the `/api` prefix so the
// FastAPI routes (which are mounted at the root, e.g. /health) match.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
