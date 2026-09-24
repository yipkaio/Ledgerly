import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// https://vite.dev/config/
export default defineConfig({
  base: "/ui/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: {
      "/ai": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
      "/bank-statements": "http://127.0.0.1:8000",
      "/dashboard": "http://127.0.0.1:8000",
      "/receipts": "http://127.0.0.1:8000",
      "/reconciliation": "http://127.0.0.1:8000",
      "/reviews": "http://127.0.0.1:8000",
    },
  },
});
