import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Built into ../dist (committed) so `mind.serve()` works with zero npm for end
// users; the Python http.server serves dist/ at the root. base:'/' gives
// ABSOLUTE asset paths so deep links like /graph/org:acme load their JS/CSS
// (a relative './assets' would resolve under the nested route and 404).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/",
  build: { outDir: "../dist", emptyOutDir: true },
  server: {
    proxy: { "/api": "http://127.0.0.1:8420" }, // `npm run dev` hits the live backend
  },
});
