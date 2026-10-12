import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  test: {
    env: { VITE_USE_MOCK_API: "true" },
    pool: "threads",
    maxWorkers: 2,
    teardownTimeout: 2000,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    testTimeout: 15000,
    restoreMocks: true,
  },
});
