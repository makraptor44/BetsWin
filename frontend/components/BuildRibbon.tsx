"use client";

import { useEffect, useState } from "react";

import { STATIC_DEMO } from "@/lib/api";
import { buildInfo } from "@/lib/build";

/**
 * Which commit is on screen.
 *
 * The deployed demo is a static export, so two branches produce two sites that
 * look the same until you read the numbers -- and the numbers are regenerated
 * fixtures, so they move on every build for reasons that have nothing to do
 * with the branch. Anyone comparing `/BetsWin/` with `/BetsWin/anthony/`
 * needs to be able to tell, without guessing, which build they are on.
 *
 * Rendered only for the static demo: a live install already knows what it is
 * running, and the page has a scanner status bar for the state that matters
 * there.
 */
export function BuildRibbon() {
  const info = buildInfo();
  const [age, setAge] = useState<string | null>(null);

  // Rendered client-side after mount. A relative timestamp computed during the
  // static export would be frozen at build time and wrong from the first view.
  useEffect(() => {
    if (!info.builtAt) return;
    const tick = () => {
      const ms = Date.now() - new Date(info.builtAt as string).getTime();
      if (!Number.isFinite(ms) || ms < 0) return setAge(null);
      const mins = Math.floor(ms / 60_000);
      if (mins < 1) return setAge("just now");
      if (mins < 60) return setAge(`${mins}m ago`);
      const hours = Math.floor(mins / 60);
      if (hours < 48) return setAge(`${hours}h ago`);
      setAge(`${Math.floor(hours / 24)}d ago`);
    };
    tick();
    const t = setInterval(tick, 30_000);
    return () => clearInterval(t);
  }, [info.builtAt]);

  if (!STATIC_DEMO) return null;

  const accent = info.isBranchDemo ? "var(--caution)" : "var(--brand)";

  return (
    <div
      className="w-full border-b text-[11px] leading-tight"
      style={{
        borderColor: "var(--border)",
        background: `color-mix(in srgb, ${accent} 12%, var(--background))`,
      }}
    >
      <div className="mx-auto flex w-full max-w-[1560px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5 sm:px-6">
        <span
          className="rounded px-1.5 py-0.5 font-mono font-semibold uppercase tracking-wide text-white"
          style={{ background: accent }}
        >
          {info.isBranchDemo ? `branch: ${info.branch}` : "main"}
        </span>

        {info.commitUrl ? (
          <a
            className="font-mono text-faint no-underline hover:underline"
            href={info.commitUrl}
            target="_blank"
            rel="noreferrer"
          >
            {info.shortSha}
          </a>
        ) : (
          <span className="font-mono text-faint">{info.shortSha}</span>
        )}

        <span className="min-w-0 flex-1 truncate text-faint" title={info.subject}>
          {info.subject}
        </span>

        {age && <span className="font-mono text-faint">built {age}</span>}

        {info.runUrl && (
          <a
            className="text-faint no-underline hover:underline"
            href={info.runUrl}
            target="_blank"
            rel="noreferrer"
          >
            build log
          </a>
        )}
      </div>
    </div>
  );
}
