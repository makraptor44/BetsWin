"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import {
  KIND_LABEL,
  money,
  num,
  pct,
} from "@/lib/format";
import type { Arb, ArbLeg } from "@/lib/types";

import { VenueChip, ZoneChip } from "./ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface PlaceBetModalProps {
  arb: Arb;
  onClose: () => void;
  onSuccess: (message?: string) => void;
}

export function PlaceBetModal({ arb, onClose, onSuccess }: PlaceBetModalProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [note, setNote] = useState("");
  const [showOverrides, setShowOverrides] = useState(false);

  // Custom executed price & stake inputs if the user experienced slight slippage
  const [customPrices, setCustomPrices] = useState<string[]>(
    arb.legs.map((l) => l.price.toString())
  );
  const [customStakes, setCustomStakes] = useState<string[]>(
    arb.legs.map((l) => l.stake.toString())
  );

  const dialogRef = useRef<HTMLDivElement>(null);
  const successTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;

      // Focus trap. The dialog declares role="dialog" aria-modal="true", which
      // promises the rest of the page is inert -- but Tab walked straight out
      // of it into the page behind, so a keyboard user could operate the
      // controls the overlay was covering.
      const root = dialogRef.current;
      if (!root) return;
      const focusable = root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  // Move focus into the dialog on open, and put it back where it came from on
  // close, so the keyboard does not lose its place.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialogRef.current
      ?.querySelector<HTMLElement>("button, input, [tabindex]")
      ?.focus();
    return () => previous?.focus?.();
  }, []);

  // Clear the success timer on unmount: it called onSuccess a second after the
  // request returned, and firing that against an unmounted tree is a state
  // update on nothing.
  useEffect(() => {
    return () => {
      if (successTimer.current) clearTimeout(successTimer.current);
    };
  }, []);

  const handlePlace = async () => {
    if (!confirmed) {
      setError("Please confirm the placement checklist before proceeding.");
      return;
    }

    setBusy(true);
    setError(null);

    try {
      const executed_prices = customPrices.map((p) => parseFloat(p) || 0);
      const executed_stakes = customStakes.map((s) => parseFloat(s) || 0);

      const res = await api.placeBet(arb.id, {
        confirmed: true,
        executed_prices: showOverrides ? executed_prices : undefined,
        executed_stakes: showOverrides ? executed_stakes : undefined,
        note: note.trim() || undefined,
        retire: true,
      });

      setSuccess(true);
      successTimer.current = setTimeout(() => {
        onSuccess(res.message);
      }, 1000);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to place bet. Please try again.",
      );
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div
        className="absolute inset-0 bg-black/65 backdrop-blur-[2px] transition-opacity"
        onClick={() => !busy && onClose()}
      />

      <div
        ref={dialogRef}
        className="relative w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh] border border-border bg-background"
      >
        {/* Header */}
        <div
          className="px-6 py-4 border-b flex items-start justify-between gap-4 bg-card border-border"
        >
          <div>
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground bg-brand-soft text-brand">{KIND_LABEL[arb.kind]}</span>
              {arb.venues.map((v) => (
                <VenueChip key={v} venue={v} />
              ))}
              <ZoneChip zone={arb.zone} short />
            </div>
            <h2 id="modal-title" className="text-base font-semibold leading-tight">
              Confirm Bet Placement: {arb.title}
            </h2>
          </div>
          <Button size="sm" variant="outline" className="shrink-0" onClick={onClose} disabled={busy} aria-label="Close" >
            ✕
          </Button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto flex flex-col gap-5">
          {success ? (
            <div
              className="p-6 rounded-xl text-center flex flex-col items-center gap-3 bg-positive-soft border border-positive"
            >
              <div
                className="w-12 h-12 rounded-full flex items-center justify-center text-2xl text-white bg-positive"
              >
                ✓
              </div>
              <h3 className="text-base font-semibold text-positive">
                Bet Placed &amp; Recorded!
              </h3>
              <p className="text-xs text-muted-foreground">
                The opportunity has been logged in your Positions ledger. Refreshing live opportunities now…
              </p>
            </div>
          ) : (
            <>
              {/* Summary Stats */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border border-border bg-card shadow-sm p-3 text-center">
                  <div className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint">Total Stake</div>
                  <div className="tabular text-base font-semibold mt-1">
                    {money(arb.total_stake, arb.currency)}
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-card shadow-sm p-3 text-center">
                  <div className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint">Guaranteed Profit</div>
                  <div className="tabular text-base font-semibold text-positive mt-1">
                    {money(arb.worst_case_profit, arb.currency)}
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-card shadow-sm p-3 text-center">
                  <div className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint">Net Margin</div>
                  <div className="tabular text-base font-semibold mt-1">
                    {pct(arb.net_margin)}
                  </div>
                </div>
              </div>

              {/* Legs Review */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint">Order Legs ({arb.legs.length})</div>
                  <button
                    type="button"
                    className="text-xs hover:underline text-brand"
                    onClick={() => setShowOverrides((o) => !o)}
                  >
                    {showOverrides ? "Hide price adjustments" : "Adjust executed prices/stakes"}
                  </button>
                </div>

                <div className="flex flex-col gap-2.5">
                  {/* `idx` addresses the positional override arrays; the
                      key is the leg's own identity. */}
                  {arb.legs.map((leg: ArbLeg, idx: number) => (
                    <div
                      key={`${leg.venue}:${leg.market_id}:${leg.outcome}`}
                      className="p-3 rounded-lg border flex flex-col gap-2 bg-muted border-border"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] py-[2px] text-[11px] font-semibold bg-neutral-soft text-muted-foreground text-xs uppercase">
                            {leg.side}
                          </span>
                          <span className="text-sm font-medium truncate">
                            {leg.outcome}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <VenueChip venue={leg.venue} />
                          {leg.url && (
                            <a
                              href={leg.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn btn-sm"
                              title={`Open market on ${leg.venue}`}
                            >
                              Open Market ↗
                            </a>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs pt-1 border-t border-border">
                        <div className="tabular text-muted-foreground">
                          Target Price: <span className="font-semibold text-white">{leg.price.toFixed(4)}</span> ({leg.decimal_odds.toFixed(2)}x)
                        </div>
                        <div className="tabular text-muted-foreground">
                          Stake: <span className="font-semibold text-white">{money(leg.stake, arb.currency)}</span> · {num(leg.contracts, 0)} contracts
                        </div>
                      </div>

                      {showOverrides && (
                        <div className="grid grid-cols-2 gap-2 pt-2 mt-1 border-t border-border">
                          <div>
                            <label className="text-[11px] block mb-1 text-faint">
                              Actual Executed Price
                            </label>
                            <Input type="number" step="0.0001" className="text-xs w-full" value={customPrices[idx] || ""} onChange={(e) => { const copy = [...customPrices]; copy[idx] = e.target.value; setCustomPrices(copy); }} />
                          </div>
                          <div>
                            <label className="text-[11px] block mb-1 text-faint">
                              Actual Executed Stake
                            </label>
                            <Input type="number" step="0.01" className="text-xs w-full" value={customStakes[idx] || ""} onChange={(e) => { const copy = [...customStakes]; copy[idx] = e.target.value; setCustomStakes(copy); }} />
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Optional Note */}
              <div>
                <label htmlFor="placement-note" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.055em] text-faint mb-1">
                  Reference Note (Optional)
                </label>
                <Input id="placement-note" type="text" placeholder="e.g. Kalshi order #9021, Smarkets session confirmation" className="w-full text-xs" value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} />
              </div>

              {/* Mandatory Confirmation Box */}
              <div
                className="p-3.5 rounded-lg border flex items-start gap-3 cursor-pointer select-none"
                style={{
                  background: confirmed ? "var(--brand-soft)" : "var(--muted)",
                  borderColor: confirmed ? "var(--brand)" : "var(--border)",
                }}
                onClick={() => !busy && setConfirmed(!confirmed)}
              >
                <input
                  type="checkbox"
                  id="confirm-checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                  disabled={busy}
                  className="mt-0.5"
                />
                <label htmlFor="confirm-checkbox" className="text-xs leading-relaxed cursor-pointer">
                  <span className="font-semibold text-white block">
                    I confirm that I have reviewed and verified all {arb.legs.length} legs.
                  </span>
                  <span className="text-muted-foreground">
                    I understand that placing this trade will record the position in my ledger and refresh the active opportunities list.
                  </span>
                </label>
              </div>

              {error && (
                <div
                  className="p-3 rounded-lg text-xs bg-danger-soft text-danger"
                >
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer Actions */}
        {!success && (
          <div
            className="px-6 py-4 border-t flex items-center justify-between gap-3 bg-card border-border"
          >
            <Button size="sm" variant="outline" type="button" onClick={onClose} disabled={busy} >
              Cancel
            </Button>
            <div className="flex items-center gap-2">
              <Button size="sm" type="button" onClick={handlePlace} disabled={busy || !confirmed} style={{ opacity: confirmed && !busy ? 1 : 0.5, minWidth: 140, }} >
                {busy ? "Placing..." : "Confirm & Place"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
