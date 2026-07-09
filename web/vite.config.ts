import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build-time flag passed as a shell env var (VITE_DEMO=1). Declared here to avoid
// pulling in @types/node just for `process`.
declare const process: { env: Record<string, string | undefined> };

// The API client calls the backend at `/api/...`. In dev, Vite proxies
// `/api` → http://localhost:8000 and strips the `/api` prefix so the
// FastAPI routes (which are mounted at the root, e.g. /health) match.
//
// The static GitHub Pages demo is built with VITE_DEMO=1; it serves from the
// repo subpath (https://<user>.github.io/ops-triage-agent/) and uses an
// in-browser mock instead of the proxy, so no backend is needed.
export default defineConfig(() => {
  const demo = process.env.VITE_DEMO === "1";
  return {
    plugins: [react()],
    base: demo ? "/ops-triage-agent/" : "/",
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
  };
});
