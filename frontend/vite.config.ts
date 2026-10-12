import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: "0.0.0.0", allowedHosts: ["terminal.local"] },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (
            /react-markdown|remark-|rehype-|micromark|mdast|hast|unist|unified|vfile/.test(
              id,
            )
          )
            return "markdown";
          if (id.includes("@radix-ui")) return "ui";
          if (/react-dom|react-router|\/react\//.test(id)) return "react";
        },
      },
    },
  },
});
