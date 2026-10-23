import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiPort = process.env.RAGCOMPASS_API_PORT ?? "8460";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5460,
    proxy: { "/api": `http://127.0.0.1:${apiPort}` },
  },
});
