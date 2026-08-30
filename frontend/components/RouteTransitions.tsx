"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/**
 * Cross-document-style transitions between routes.
 *
 * Next's client router swaps the tree with no visual continuity: the old page
 * is gone and the new one is simply there. On a dashboard where every page
 * shares a header, a stat row and a table, that discontinuity reads as a reload
 * even though nothing was fetched.
 *
 * The View Transitions API handles the animation itself -- the browser
 * snapshots the old frame, snapshots the new one, and cross-fades between them
 * on the compositor. All this component does is make the router's DOM swap
 * happen *inside* `startViewTransition`, and mark the shell so it stays put
 * while the content moves.
 *
 * Progressive by construction: browsers without the API run the plain swap, and
 * a user who has asked for reduced motion gets it too, because the transition
 * is suppressed in CSS rather than here.
 */
export function RouteTransitions() {
  const pathname = usePathname();

  useEffect(() => {
    // The class is what the ::view-transition-* rules in globals.css hang off,
    // so the animation only applies to a navigation and never to the initial
    // paint -- where it would show as an unexplained fade on first load.
    const root = document.documentElement;
    root.classList.add("route-changed");
    const t = window.setTimeout(() => root.classList.remove("route-changed"), 500);
    return () => window.clearTimeout(t);
  }, [pathname]);

  return null;
}

/**
 * Wraps a navigation in a view transition.
 *
 * Exported for `<TransitionLink>` below and for any imperative navigation that
 * wants the same treatment.
 */
export function withViewTransition(navigate: () => void): void {
  const doc = document as Document & {
    startViewTransition?: (cb: () => void) => { finished: Promise<void> };
  };
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (reduced || typeof doc.startViewTransition !== "function") {
    navigate();
    return;
  }
  doc.startViewTransition(navigate);
}
