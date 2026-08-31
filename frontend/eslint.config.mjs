import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

/**
 * ESLint, flat config.
 *
 * `package.json` declared `"lint": "next lint"` while the repo contained no
 * ESLint configuration and no ESLint dependency, so the script could not run at
 * all -- and `next lint` is gone in Next 16 regardless, in favour of the ESLint
 * CLI. This is the replacement.
 *
 * eslint-config-next 16 exports flat config directly, so there is no
 * FlatCompat shim here.
 */
const config = [
  {
    ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts"],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      // `catch (e: any)` is the usual way this one gets ignored, and it hides
      // the fact that a thrown value might not be an Error at all.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // The dependency-array bugs this catches are exactly the class of thing
      // that made `useAsync` throw on a variable-length list.
      "react-hooks/exhaustive-deps": "warn",

      // React 19's new strictness about setState inside an effect. Every hit in
      // this codebase is the ordinary "fetch on mount, then setState" idiom,
      // and satisfying the rule properly means moving data loading to Suspense
      // or a query library -- a restructure, not a fix. Kept as a warning so
      // the signal survives without failing the build on a known, deliberate
      // gap.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default config;
