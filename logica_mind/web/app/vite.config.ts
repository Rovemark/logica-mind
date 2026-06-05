import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Built into ../dist (committed) so `mind.serve()` works with zero npm for end
// users; the Python http.server serves dist/. base:'./' keeps asset paths
// relative so it works under any mount point.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  build: { outDir: "../dist", emptyOutDir: true },
  server: {
    proxy: { "/api": "http://127.0.0.1:8420" }, // `npm run dev` hits the live backend
  },
});
