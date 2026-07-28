import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Some Linux setups miss inotify file events; polling is slower but reliable.
    watch: { usePolling: true },
    // Same-origin trick: the browser only ever talks to :5173. Vite forwards
    // /api/* to Django, so the HttpOnly refresh cookie is first-party and no
    // CORS is involved — exactly how Nginx serves it in production.
    proxy: {
      // Port 8000 on this machine belongs to another project's Docker nginx,
      // so ClientHub's Django runs on 8002: manage.py runserver 8002
      "/api": {
        target: "http://localhost:8002",
        changeOrigin: true,
      },
    },
  },
});
