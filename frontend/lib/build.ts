/**
 * Build provenance.
 *
 * The deployed demo is a static export with no backend behind it, so nothing in
 * the page can tell you *which* commit produced the numbers you are looking at.
 * That is fine when one branch deploys; it is actively misleading once several
 * do, because two builds of two different branches are byte-similar enough to
 * look identical at a glance.
 *
 * CI stamps these at build time (see .github/workflows/deploy-demo.yml). They
 * are NEXT_PUBLIC_* so they are inlined into the client bundle -- they are
 * public facts about a public repository, not secrets.
 */

const env = (key: string, fallback: string): string => {
  // Next inlines process.env.NEXT_PUBLIC_* by literal match, so these cannot be
  // looked up dynamically -- each one has to be written out.
  const table: Record<string, string | undefined> = {
    NEXT_PUBLIC_BUILD_BRANCH: process.env.NEXT_PUBLIC_BUILD_BRANCH,
    NEXT_PUBLIC_BUILD_SHA: process.env.NEXT_PUBLIC_BUILD_SHA,
    NEXT_PUBLIC_BUILD_TIME: process.env.NEXT_PUBLIC_BUILD_TIME,
    NEXT_PUBLIC_BUILD_SUBJECT: process.env.NEXT_PUBLIC_BUILD_SUBJECT,
    NEXT_PUBLIC_BUILD_REPO: process.env.NEXT_PUBLIC_BUILD_REPO,
    NEXT_PUBLIC_BUILD_RUN_URL: process.env.NEXT_PUBLIC_BUILD_RUN_URL,
  };
  const value = table[key];
  return value && value.length > 0 ? value : fallback;
};

export interface BuildInfo {
  branch: string;
  sha: string;
  shortSha: string;
  builtAt: string | null;
  subject: string;
  repo: string;
  /** Link to the exact commit this bundle was built from. */
  commitUrl: string | null;
  runUrl: string | null;
  /** False for `main`; drives the "this is not the default demo" styling. */
  isBranchDemo: boolean;
}

export function buildInfo(): BuildInfo {
  const branch = env("NEXT_PUBLIC_BUILD_BRANCH", "local");
  const sha = env("NEXT_PUBLIC_BUILD_SHA", "");
  const repo = env("NEXT_PUBLIC_BUILD_REPO", "makraptor44/BetsWin");
  const builtAt = env("NEXT_PUBLIC_BUILD_TIME", "");
  const runUrl = env("NEXT_PUBLIC_BUILD_RUN_URL", "");

  return {
    branch,
    sha,
    shortSha: sha ? sha.slice(0, 7) : "unknown",
    builtAt: builtAt || null,
    subject: env("NEXT_PUBLIC_BUILD_SUBJECT", "uncommitted working tree"),
    repo,
    commitUrl: sha ? `https://github.com/${repo}/commit/${sha}` : null,
    runUrl: runUrl || null,
    isBranchDemo: branch !== "main" && branch !== "local",
  };
}
