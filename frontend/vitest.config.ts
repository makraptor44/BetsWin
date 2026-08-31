import { defineConfig } from "vitest/config";

/**
 * The repo had no frontend test runner at all. This exists mainly so the
 * TypeScript port of the odds arithmetic can be checked against the same
 * vectors the Python suite uses -- see `shared/odds-vectors.json`.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/__tests__/**/*.test.ts"],
  },
});
