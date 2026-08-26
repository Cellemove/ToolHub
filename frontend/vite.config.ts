import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// no @types/node in this project; enough typing for the env override below
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.TOOLHUB_API ?? "http://127.0.0.1:8000" },
  },
});
