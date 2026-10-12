import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The dev server forwards API calls to Flask, so the browser sees one
    // origin and no CORS setup is needed. Production does the same thing
    // for real: Flask serves the built files and the API together.
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  test: { environment: "node" },
});
